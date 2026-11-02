//! Run setup shared by every entry point, mirroring `think_tank/runner.py`.

use std::collections::BTreeMap;

use crate::kb::{get_vector_store, seed_if_empty, VectorStore};
use crate::llm::missing_credentials;
use crate::state::ThinkTankState;
use crate::telemetry::span;

/// Convergence defaults for a deliberation run.
pub const DEFAULT_ALIGNMENT_THRESHOLD: f64 = 0.65;
pub const DEFAULT_MIN_ROUNDS: u32 = 2;
pub const DEFAULT_MAX_ROUNDS: u32 = 6;

/// Runtime config: convergence knobs plus optional per-agent overrides.
#[derive(Debug, Clone, Default)]
pub struct Config {
    pub values: BTreeMap<String, String>,
}

impl Config {
    pub fn new() -> Self {
        Self::default()
    }

    /// Layer `overrides` on top of `self`, caller's map never mutated.
    pub fn with_overrides(mut self, overrides: &BTreeMap<String, String>) -> Self {
        for (key, value) in overrides {
            self.values.insert(key.clone(), value.clone());
        }
        self
    }

    pub fn get(&self, key: &str) -> Option<&str> {
        self.values.get(key).map(|s| s.as_str())
    }

    pub fn alignment_threshold(&self) -> f64 {
        self.get("alignment_threshold")
            .and_then(|v| v.parse().ok())
            .unwrap_or(DEFAULT_ALIGNMENT_THRESHOLD)
    }

    pub fn min_rounds_or(&self, fallback: u32) -> u32 {
        self.get("min_rounds")
            .and_then(|v| v.parse().ok())
            .unwrap_or(fallback)
    }

    pub fn max_rounds_or(&self, fallback: u32) -> u32 {
        self.get("max_rounds")
            .and_then(|v| v.parse().ok())
            .unwrap_or(fallback)
    }

    pub fn min_rounds(&self) -> u32 {
        self.get("min_rounds")
            .and_then(|v| v.parse().ok())
            .unwrap_or(DEFAULT_MIN_ROUNDS)
    }

    pub fn max_rounds(&self) -> u32 {
        self.get("max_rounds")
            .and_then(|v| v.parse().ok())
            .unwrap_or(DEFAULT_MAX_ROUNDS)
    }

    pub fn agent_provider(&self, agent: &str) -> Option<&str> {
        self.get(&format!("{}_provider", agent))
    }

    pub fn agent_model(&self, agent: &str) -> Option<&str> {
        self.get(&format!("{}_model", agent))
    }

    pub fn agent_max_tokens(&self, key_agent: &str) -> Option<u32> {
        self.get(&format!("{}_max_tokens", key_agent))
            .and_then(|v| v.parse().ok())
    }

    pub fn agent_reasoning_effort(&self, agent: &str) -> Option<&str> {
        self.get(&format!("{}_reasoning_effort", agent))
    }
}

#[derive(Debug)]
pub struct MissingCredentialsError {
    pub missing: Vec<String>,
}

impl std::fmt::Display for MissingCredentialsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.missing.join(", "))
    }
}

impl std::error::Error for MissingCredentialsError {}

/// Build the state a deliberation starts from.
pub fn initial_state(topic: &str, config: Option<Config>) -> ThinkTankState {
    ThinkTankState {
        topic: topic.to_string(),
        config: config.unwrap_or_default(),
        claims: Vec::new(),
        challenges: Vec::new(),
        expansions: Vec::new(),
        syntheses: Vec::new(),
        current_round: 0,
        alignment_score: 0.0,
        expansion: None,
        synthesis: None,
        evidence: String::new(),
    }
}

/// Raise when a provider key is unset.
pub fn require_credentials() -> Result<(), MissingCredentialsError> {
    let missing = missing_credentials().unwrap_or_default();
    if missing.is_empty() {
        Ok(())
    } else {
        Err(MissingCredentialsError { missing })
    }
}

/// Result of `prepare_run` — a live vector store, seeded if needed.
pub struct PreparedRun {
    pub vector_store: VectorStore,
    pub seeded: bool,
}

/// Check credentials, open the vector store, and seed it when empty.
pub fn prepare_run() -> Result<PreparedRun, PrepareError> {
    require_credentials()?;
    let vector_store = span("startup.vector_store", "startup", get_vector_store)
        .map_err(PrepareError::VectorStore)?;
    let seeded = span("startup.seed", "startup", || seed_if_empty(&vector_store))
        .map_err(PrepareError::VectorStore)?;
    Ok(PreparedRun {
        vector_store,
        seeded,
    })
}

#[derive(Debug)]
pub enum PrepareError {
    Missing(MissingCredentialsError),
    VectorStore(String),
}

impl From<MissingCredentialsError> for PrepareError {
    fn from(value: MissingCredentialsError) -> Self {
        PrepareError::Missing(value)
    }
}

impl std::fmt::Display for PrepareError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PrepareError::Missing(e) => write!(f, "Missing credentials: {}", e),
            PrepareError::VectorStore(e) => write!(f, "vector store: {}", e),
        }
    }
}
