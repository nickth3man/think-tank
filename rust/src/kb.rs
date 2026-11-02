//! Knowledge base, mirroring `think_tank/kb.py`.
//!
//! The Python implementation persists Chroma (HNSW over SQLite). Reimplementing
//! that binary format in Rust would buy nothing the app depends on: the only
//! operations are "is the collection empty", "add documents", and "top-k
//! similarity search". This module keeps those three semantics with a plain
//! JSON collection file per embedding space, under `THINK_TANK_KB_PATH`
//! (default `./kb_store`). Chroma's SQLite/HNSW files are deliberately not
//! touched: this store cannot read that format, and the legacy `chroma_db/`
//! directory belongs to the previous implementation.

use std::collections::BTreeMap;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::llm::{
    embed_documents, embed_query, embedding_collection_name, embedding_model,
    resolve_embedding_provider,
};
use crate::telemetry::span;

pub const SEED_DOCUMENTS: &[&str] = &[
    "Remote work has been shown to increase productivity for knowledge workers by 13% according to a Stanford study conducted over 9 months with 16,000 employees. The increase was attributed to quieter work environments and fewer sick days.",
    "A 2023 McKinsey report found that 87% of workers offered flexible work arrangements choose to work remotely at least part of the time. Employee satisfaction scores rose by 20% when remote options were available.",
    "Communication overhead increases by approximately 30% in fully remote teams due to reliance on asynchronous channels, according to a Microsoft study of 60,000 employees. This can lead to slower decision-making in time-sensitive situations.",
    "Hybrid work models (2-3 days in-office) appear to balance productivity gains with team cohesion. A Harvard Business Review meta-analysis of 45 studies found hybrid arrangements produced optimal outcomes for both employee well-being and business metrics.",
    "Remote work exacerbates the 'always-on' culture: 62% of remote workers report difficulty disconnecting after work hours (Buffer State of Remote Work 2023). This can lead to burnout despite apparent schedule flexibility.",
    "Innovation metrics decline in fully remote settings according to a Nature Human Behaviour study analysing 20 million research papers. Face-to-face interactions were found to be significantly more likely to produce novel, breakthrough ideas compared to virtual collaboration.",
    "Cost savings from remote work are substantial: companies save an average of $11,000 per remote employee per year on real estate, utilities, and office supplies (Global Workplace Analytics 2023 estimate).",
    "Onboarding new employees remotely takes 32% longer on average compared to in-person onboarding, according to a 2022 Gartner survey of 500 HR leaders. Knowledge transfer and culture assimilation were cited as the primary challenges.",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredDocument {
    pub id: String,
    pub text: String,
    pub embedding: Vec<f64>,
    #[serde(default)]
    pub metadata: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Collection {
    pub name: String,
    pub documents: Vec<StoredDocument>,
}

/// An open collection bound to one embedding space.
#[derive(Debug, Clone)]
pub struct VectorStore {
    pub collection: Collection,
    path: PathBuf,
    provider: &'static crate::llm::Provider,
    model: String,
}

fn base_dir() -> PathBuf {
    PathBuf::from(
        std::env::var("THINK_TANK_KB_PATH")
            .ok()
            .filter(|v| !v.is_empty())
            .unwrap_or_else(|| "./kb_store".to_string()),
    )
}

fn collection_path(name: &str) -> PathBuf {
    base_dir().join(format!("{}.json", name))
}

fn load(path: &Path, name: &str) -> Result<Collection, String> {
    if !path.exists() {
        return Ok(Collection {
            name: name.to_string(),
            documents: Vec::new(),
        });
    }
    let raw =
        std::fs::read_to_string(path).map_err(|e| format!("reading {}: {}", path.display(), e))?;
    if raw.trim().is_empty() {
        return Ok(Collection {
            name: name.to_string(),
            documents: Vec::new(),
        });
    }
    serde_json::from_str(&raw).map_err(|e| format!("parsing {}: {}", path.display(), e))
}

impl VectorStore {
    pub fn save(&self) -> Result<(), String> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("creating {}: {}", parent.display(), e))?;
        }
        let payload = serde_json::to_vec_pretty(&self.collection)
            .map_err(|e| format!("serialising collection: {}", e))?;
        let tmp = self.path.with_extension("json.tmp");
        {
            let mut file = std::fs::File::create(&tmp)
                .map_err(|e| format!("writing {}: {}", tmp.display(), e))?;
            file.write_all(&payload)
                .map_err(|e| format!("writing {}: {}", tmp.display(), e))?;
            file.flush()
                .map_err(|e| format!("flushing {}: {}", tmp.display(), e))?;
        }
        std::fs::rename(&tmp, &self.path)
            .map_err(|e| format!("renaming into {}: {}", self.path.display(), e))
    }

    /// Cheap emptiness probe — no embedding round trip.
    pub fn is_empty(&self) -> bool {
        self.collection.documents.is_empty()
    }

    pub fn add_documents(
        &mut self,
        docs: Vec<(String, String, BTreeMap<String, serde_json::Value>)>,
    ) -> Result<(), String> {
        let texts: Vec<String> = docs.iter().map(|(_, text, _)| text.clone()).collect();
        let vectors = embed_documents(self.provider, &self.model, &texts)?;
        for ((id, text, metadata), embedding) in docs.into_iter().zip(vectors) {
            self.collection.documents.push(StoredDocument {
                id,
                text,
                embedding,
                metadata,
            });
        }
        self.save()
    }

    /// Top-k similarity search by cosine similarity, highest first.
    pub fn similarity_search(&self, query: &str, k: usize) -> Result<Vec<StoredDocument>, String> {
        Ok(self
            .similarity_search_scored(query, k)?
            .into_iter()
            .map(|(_, doc)| doc)
            .collect())
    }

    /// Same ranking as [`similarity_search`](Self::similarity_search), keeping each score.
    pub fn similarity_search_scored(
        &self,
        query: &str,
        k: usize,
    ) -> Result<Vec<(f64, StoredDocument)>, String> {
        if self.collection.documents.is_empty() {
            return Ok(Vec::new());
        }
        let query_embedding = embed_query(query)?;
        let mut scored: Vec<(f64, &StoredDocument)> = self
            .collection
            .documents
            .iter()
            .map(|doc| (cosine_similarity(&query_embedding, &doc.embedding), doc))
            .collect();
        scored.sort_by(|a, b| b.0.total_cmp(&a.0));
        Ok(scored
            .into_iter()
            .take(k)
            .map(|(score, doc)| (score, doc.clone()))
            .collect())
    }
}

fn cosine_similarity(a: &[f64], b: &[f64]) -> f64 {
    if a.is_empty() || b.is_empty() || a.len() != b.len() {
        return 0.0;
    }
    let dot: f64 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let norm_a = a.iter().map(|x| x * x).sum::<f64>().sqrt();
    let norm_b = b.iter().map(|x| x * x).sum::<f64>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }
    dot / (norm_a * norm_b)
}

/// Open the persistent collection for the active embedding space.
pub fn get_vector_store() -> Result<VectorStore, String> {
    let name = embedding_collection_name(None, None)?;
    let provider = resolve_embedding_provider(None)?;
    let model = embedding_model(provider, None);
    let path = collection_path(&name);
    let collection = load(&path, &name)?;
    Ok(VectorStore {
        collection,
        path,
        provider,
        model,
    })
}

fn seed_documents() -> Vec<(String, String, BTreeMap<String, serde_json::Value>)> {
    SEED_DOCUMENTS
        .iter()
        .enumerate()
        .map(|(i, text)| {
            let mut metadata = BTreeMap::new();
            metadata.insert("source".to_string(), serde_json::json!("seed"));
            metadata.insert("index".to_string(), serde_json::json!(i));
            (format!("seed-{}", i), text.to_string(), metadata)
        })
        .collect()
}

/// Populate the collection with the seed documents when it is empty.
pub fn seed_if_empty(vector_store: &VectorStore) -> Result<bool, String> {
    let empty = span("kb.seed.check", "vector_store", || vector_store.is_empty());
    if !empty {
        return Ok(false);
    }
    span("kb.seed.load", "vector_store", || {
        let mut store = vector_store.clone();
        store.add_documents(seed_documents())
    })
    .map(|_| true)
}

/// Similarity-search the knowledge base and join the matched passages.
pub fn retrieve(topic: &str, k: usize) -> Result<String, String> {
    let store = get_vector_store()?;
    let results = span("kb.retrieve", "vector_store", || {
        store.similarity_search(topic, k)
    })?;
    if results.is_empty() {
        return Ok(format!("No pre-indexed documents found for: {:?}.", topic));
    }
    Ok(results
        .into_iter()
        .map(|doc| doc.text)
        .collect::<Vec<_>>()
        .join("\n"))
}
