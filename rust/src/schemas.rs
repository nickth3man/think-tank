//! Shared state models, mirroring `think_tank/schemas.py`.
//!
//! Field order and JSON shape follow the pydantic models exactly so a state
//! recorded from the Python implementation can be compared byte-for-byte with
//! the Rust one.

use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize, Serializer};

/// Serialize a timestamp the way pydantic renders an aware datetime:
/// `2026-01-02T03:04:05Z`, or `...05.123456Z` when microseconds are non-zero.
fn serialize_ts<S: Serializer>(ts: &DateTime<Utc>, s: S) -> Result<S::Ok, S::Error> {
    if ts.timestamp_subsec_micros() == 0 {
        s.serialize_str(&ts.to_rfc3339_opts(SecondsFormat::Secs, true))
    } else {
        s.serialize_str(&ts.to_rfc3339_opts(SecondsFormat::Micros, true))
    }
}

/// Insertion-ordered string map, matching pydantic's `dict[str, str]`.
///
/// Serialization keeps first-insertion order, so a `dimensions` payload
/// recorded by the Python implementation round-trips byte-for-byte.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Dimensions(Vec<(String, String)>);

impl Dimensions {
    pub fn new() -> Self {
        Self(Vec::new())
    }

    /// Insert like Python's `dict.__setitem__`: existing keys keep their
    /// position and take the new value.
    pub fn insert(&mut self, key: String, value: String) {
        if let Some(slot) = self.0.iter_mut().find(|(k, _)| *k == key) {
            slot.1 = value;
        } else {
            self.0.push((key, value));
        }
    }

    pub fn iter(&self) -> impl Iterator<Item = (&String, &String)> {
        self.0.iter().map(|(k, v)| (k, v))
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }
}

/// Python's `str.__repr__`, which is what `str(dict)` uses for each key/value.
///
/// CPython picks single quotes unless the string contains `'` and no `"`, in
/// which case it switches to double quotes; it then escapes the other quote
/// character, the backslash, and the usual control escapes. Dimension values
/// from real models routinely contain apostrophes, so getting this wrong would
/// change the prompt text the Skeptic sees.
fn py_str_repr(value: &str) -> String {
    let has_single = value.contains('\'');
    let has_double = value.contains('"');
    let quote = if has_single && !has_double { '"' } else { '\'' };
    let mut out = String::with_capacity(value.len() + 2);
    out.push(quote);
    for c in value.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if c.is_control() => out.push_str(&format!("\\x{:02x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

impl std::fmt::Display for Dimensions {
    /// Renders the way Python's `str(dict)` does inside an f-string, which is
    /// what the Skeptic prompt embeds.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("{")?;
        for (i, (k, v)) in self.0.iter().enumerate() {
            if i > 0 {
                f.write_str(", ")?;
            }
            f.write_str(&py_str_repr(k))?;
            f.write_str(": ")?;
            f.write_str(&py_str_repr(v))?;
        }
        f.write_str("}")
    }
}

impl Serialize for Dimensions {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeMap;
        let mut map = s.serialize_map(Some(self.0.len()))?;
        for (k, v) in &self.0 {
            map.serialize_entry(k, v)?;
        }
        map.end()
    }
}

impl<'de> Deserialize<'de> for Dimensions {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let raw = serde_json::Map::<String, serde_json::Value>::deserialize(d)?;
        Ok(stringify_dimensions(Some(&serde_json::Value::Object(raw))))
    }
}

pub fn now() -> DateTime<Utc> {
    Utc::now()
}

pub fn new_id() -> String {
    uuid::Uuid::new_v4().to_string()
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Confidence {
    Low,
    #[default]
    Medium,
    High,
}

impl Confidence {
    pub fn as_str(self) -> &'static str {
        match self {
            Confidence::Low => "low",
            Confidence::Medium => "medium",
            Confidence::High => "high",
        }
    }
}

impl std::fmt::Display for Confidence {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Stance {
    Support,
    Oppose,
    Refine,
}

impl Stance {
    pub fn as_str(self) -> &'static str {
        match self {
            Stance::Support => "support",
            Stance::Oppose => "oppose",
            Stance::Refine => "refine",
        }
    }
}

impl std::fmt::Display for Stance {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// An assertion or position put forward by an agent.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Claim {
    pub id: String,
    pub agent_id: String,
    pub round: u32,
    pub content: String,
    pub dimensions: Dimensions,
    pub confidence: Confidence,
    pub evidence_summary: String,
    pub embedding: Vec<f64>,
    #[serde(serialize_with = "serialize_ts")]
    pub created_at: DateTime<Utc>,
}

/// A counter-argument, support, or refinement targeting a specific claim.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Challenge {
    pub id: String,
    pub agent_id: String,
    pub target_claim_id: String,
    pub round: u32,
    pub stance: Stance,
    pub content: String,
    pub reasoning: String,
    pub resolved: bool,
    #[serde(serialize_with = "serialize_ts")]
    pub created_at: DateTime<Utc>,
}

/// An unconventional idea or perspective expansion proposed by the Visionary.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LateralIdea {
    pub id: String,
    pub agent_id: String,
    pub round: u32,
    pub content: String,
    pub related_claim_ids: Vec<String>,
    pub novelty_rationale: String,
    #[serde(serialize_with = "serialize_ts")]
    pub created_at: DateTime<Utc>,
}

/// A per-round attempt to merge perspectives and resolve contradictions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SynthesisAttempt {
    pub id: String,
    pub agent_id: String,
    pub round: u32,
    pub content: String,
    pub incorporated_claim_ids: Vec<String>,
    pub resolved_tensions: Vec<String>,
    pub remaining_tensions: Vec<String>,
    pub confidence: Confidence,
    #[serde(serialize_with = "serialize_ts")]
    pub created_at: DateTime<Utc>,
}

/// Directive from the Arbiter requesting agents to elaborate on weak spots.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Expansion {
    pub id: String,
    pub round: u32,
    pub focus_dimensions: Vec<String>,
    pub prompt: String,
    pub disagreement_summary: String,
    #[serde(serialize_with = "serialize_ts")]
    pub created_at: DateTime<Utc>,
}

/// The converged, merged output when agents reach alignment.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Synthesis {
    pub id: String,
    pub content: String,
    pub contributing_claim_ids: Vec<String>,
    pub alignment_score: f64,
    pub rounds_taken: u32,
    pub unresolved_challenges: Vec<String>,
    #[serde(serialize_with = "serialize_ts")]
    pub created_at: DateTime<Utc>,
}

// ---------------------------------------------------------------------------
// Dimension coercion — mirrors `_stringify_dimensions`
// ---------------------------------------------------------------------------

/// Render one dimension's value as a single readable string.
fn flatten_dimension_value(raw: &serde_json::Value) -> String {
    match raw {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Object(map) => map
            .iter()
            .filter(|(_, v)| !matches!(v, serde_json::Value::Null))
            .filter(|(_, v)| !matches!(v, serde_json::Value::String(s) if s.is_empty()))
            .map(|(k, v)| format!("{}: {}", k, scalar_text(v)))
            .collect::<Vec<_>>()
            .join("; "),
        serde_json::Value::Array(items) => items
            .iter()
            .map(flatten_dimension_value)
            .collect::<Vec<_>>()
            .join("; "),
        serde_json::Value::Null => String::new(),
        other => scalar_text(other),
    }
}

/// `str(value)` for the JSON scalars pydantic would render.
fn scalar_text(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Bool(b) => {
            if *b {
                "True".to_string()
            } else {
                "False".to_string()
            }
        }
        serde_json::Value::Null => "None".to_string(),
        serde_json::Value::Number(n) => n.to_string(),
        serde_json::Value::Array(items) => items
            .iter()
            .map(flatten_dimension_value)
            .collect::<Vec<_>>()
            .join(", "),
        serde_json::Value::Object(map) => map
            .iter()
            .map(|(k, v)| format!("{}: {}", k, scalar_text(v)))
            .collect::<Vec<_>>()
            .join("; "),
    }
}

/// Coerce loosely-shaped dimension payloads into `map<string, string>`.
///
/// Models emit this field in several shapes: a flat string map, a nested
/// `{"feasibility": {"rating": "high"}}` map, or a JSON-encoded string of
/// either. All of them are flattened instead of failing the whole structured
/// call; anything else is dropped.
pub fn stringify_dimensions(value: Option<&serde_json::Value>) -> Dimensions {
    let Some(value) = value else {
        return Dimensions::new();
    };
    let owned;
    let value: &serde_json::Value = match value {
        serde_json::Value::String(s) => match serde_json::from_str::<serde_json::Value>(s) {
            Ok(parsed) => {
                owned = parsed;
                &owned
            }
            Err(_) => return Dimensions::new(),
        },
        other => other,
    };
    match value {
        serde_json::Value::Array(items) => {
            let mut out = Dimensions::new();
            for item in items {
                if let serde_json::Value::Array(pair) = item {
                    if pair.len() == 2 {
                        if let Some(key) = pair.first().map(scalar_text) {
                            out.insert(key, flatten_dimension_value(&pair[1]));
                        }
                    }
                }
            }
            out
        }
        serde_json::Value::Object(map) => {
            let mut out = Dimensions::new();
            for (k, v) in map {
                out.insert(k.clone(), flatten_dimension_value(v));
            }
            out
        }
        _ => Dimensions::new(),
    }
}

// ---------------------------------------------------------------------------
// LLM output models — validated after each structured call
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct ResearcherOutput {
    pub content: String,
    pub dimensions: Dimensions,
    pub confidence: Confidence,
    pub evidence_summary: String,
}

#[derive(Debug, Clone)]
pub struct SkepticOutput {
    pub target_claim_id: String,
    pub stance: Stance,
    pub content: String,
    pub reasoning: String,
}

#[derive(Debug, Clone)]
pub struct VisionaryOutput {
    pub content: String,
    pub related_claim_ids: Vec<String>,
    pub novelty_rationale: String,
}

#[derive(Debug, Clone)]
pub struct SynthesizerOutput {
    pub content: String,
    pub incorporated_claim_ids: Vec<String>,
    pub resolved_tensions: Vec<String>,
    pub remaining_tensions: Vec<String>,
    pub confidence: Confidence,
}

/// Which structured schema an agent binds to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SchemaKind {
    Researcher,
    Skeptic,
    Visionary,
    Synthesizer,
}

impl SchemaKind {
    pub fn name(self) -> &'static str {
        match self {
            SchemaKind::Researcher => "ResearcherOutput",
            SchemaKind::Skeptic => "SkepticOutput",
            SchemaKind::Visionary => "VisionaryOutput",
            SchemaKind::Synthesizer => "SynthesizerOutput",
        }
    }

    /// JSON schema advertised to the model, matching the pydantic model.
    pub fn json_schema(self) -> serde_json::Value {
        let (props, required) = match self {
            SchemaKind::Researcher => (
                serde_json::json!({
                    "content": {"type": "string", "description": "Evidence-grounded claim text."},
                    "dimensions": {"type": "object", "additionalProperties": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "evidence_summary": {"type": "string"}
                }),
                vec!["content", "evidence_summary"],
            ),
            SchemaKind::Skeptic => (
                serde_json::json!({
                    "target_claim_id": {"type": "string"},
                    "stance": {"type": "string", "enum": ["support", "oppose", "refine"]},
                    "content": {"type": "string"},
                    "reasoning": {"type": "string"}
                }),
                vec!["target_claim_id", "stance", "content", "reasoning"],
            ),
            SchemaKind::Visionary => (
                serde_json::json!({
                    "content": {"type": "string"},
                    "related_claim_ids": {"type": "array", "items": {"type": "string"}},
                    "novelty_rationale": {"type": "string"}
                }),
                vec!["content", "novelty_rationale"],
            ),
            SchemaKind::Synthesizer => (
                serde_json::json!({
                    "content": {"type": "string"},
                    "incorporated_claim_ids": {"type": "array", "items": {"type": "string"}},
                    "resolved_tensions": {"type": "array", "items": {"type": "string"}},
                    "remaining_tensions": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]}
                }),
                vec!["content"],
            ),
        };
        serde_json::json!({
            "type": "object",
            "title": self.name(),
            "properties": props,
            "required": required,
        })
    }
}

fn as_str_field(v: &serde_json::Value, key: &str, min_len: usize) -> Result<String, String> {
    let raw = v
        .get(key)
        .and_then(|x| x.as_str())
        .ok_or_else(|| format!("{key}: field required"))?;
    if raw.chars().count() < min_len {
        return Err(format!("{key}: string too short"));
    }
    Ok(raw.to_string())
}

fn string_list(v: &serde_json::Value, key: &str) -> Vec<String> {
    v.get(key)
        .and_then(|x| x.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|i| i.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

fn confidence_of(v: &serde_json::Value) -> Confidence {
    match v.get("confidence").and_then(|c| c.as_str()) {
        Some("low") => Confidence::Low,
        Some("high") => Confidence::High,
        _ => Confidence::Medium,
    }
}

fn stance_of(v: &serde_json::Value) -> Result<Stance, String> {
    match v.get("stance").and_then(|c| c.as_str()) {
        Some("support") => Ok(Stance::Support),
        Some("oppose") => Ok(Stance::Oppose),
        Some("refine") => Ok(Stance::Refine),
        other => Err(format!("stance: invalid value {other:?}")),
    }
}

impl ResearcherOutput {
    pub fn parse(v: &serde_json::Value) -> Result<Self, String> {
        Ok(ResearcherOutput {
            content: as_str_field(v, "content", 10)?,
            dimensions: stringify_dimensions(v.get("dimensions")),
            confidence: confidence_of(v),
            evidence_summary: as_str_field(v, "evidence_summary", 5)?,
        })
    }
}

impl SkepticOutput {
    pub fn parse(v: &serde_json::Value) -> Result<Self, String> {
        Ok(SkepticOutput {
            target_claim_id: as_str_field(v, "target_claim_id", 1)?,
            stance: stance_of(v)?,
            content: as_str_field(v, "content", 10)?,
            reasoning: as_str_field(v, "reasoning", 10)?,
        })
    }
}

impl VisionaryOutput {
    pub fn parse(v: &serde_json::Value) -> Result<Self, String> {
        Ok(VisionaryOutput {
            content: as_str_field(v, "content", 10)?,
            related_claim_ids: string_list(v, "related_claim_ids"),
            novelty_rationale: as_str_field(v, "novelty_rationale", 10)?,
        })
    }
}

impl SynthesizerOutput {
    pub fn parse(v: &serde_json::Value) -> Result<Self, String> {
        Ok(SynthesizerOutput {
            content: as_str_field(v, "content", 10)?,
            incorporated_claim_ids: string_list(v, "incorporated_claim_ids"),
            resolved_tensions: string_list(v, "resolved_tensions"),
            remaining_tensions: string_list(v, "remaining_tensions"),
            confidence: confidence_of(v),
        })
    }
}

/// Validate a raw structured payload against the schema the agent bound to.
pub fn parse_output(kind: SchemaKind, v: &serde_json::Value) -> Result<serde_json::Value, String> {
    match kind {
        SchemaKind::Researcher => ResearcherOutput::parse(v).map(|_| v.clone()),
        SchemaKind::Skeptic => SkepticOutput::parse(v).map(|_| v.clone()),
        SchemaKind::Visionary => VisionaryOutput::parse(v).map(|_| v.clone()),
        SchemaKind::Synthesizer => SynthesizerOutput::parse(v).map(|_| v.clone()),
    }
}
