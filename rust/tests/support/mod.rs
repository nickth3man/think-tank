//! Shared test harness: a local OpenAI-protocol stub server.
//!
//! The stub answers `/chat/completions` from a scripted list of structured
//! payloads and `/embeddings` with the same FNV-based hash embedding the Python
//! golden recorder used, so both implementations see identical model output and
//! identical vectors without any network call or credential.

#![allow(dead_code)]

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{LazyLock, Mutex, MutexGuard};

use serde_json::{json, Value};

// ---------------------------------------------------------------------------
// Deterministic embedding — must match `embed()` in record_python_golden.py
// ---------------------------------------------------------------------------

const DIMS: usize = 8;

fn fnv1a(data: &[u8]) -> u64 {
    let mut hash: u64 = 0xCBF29CE484222325;
    for byte in data {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x100000001B3);
    }
    hash
}

/// Hash embedding used by the Python recorder.
pub fn hash_embed(text: &str) -> Vec<f64> {
    (0..DIMS)
        .map(|i| {
            let h = fnv1a(format!("{}:{}", i, text).as_bytes());
            (h as f64 / u64::MAX as f64) * 2.0 - 1.0
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Script state
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct ScriptEntry {
    pub schema: String,
    pub payload: Value,
}

#[derive(Default)]
pub struct StubState {
    script: Vec<ScriptEntry>,
    cursor: usize,
    /// Schema names in the order the server received structured calls.
    call_order: Vec<String>,
    /// Every user message the server received, in order.
    user_messages: Vec<String>,
}

fn state() -> &'static Mutex<StubState> {
    static STATE: LazyLock<Mutex<StubState>> = LazyLock::new(|| Mutex::new(StubState::default()));
    &STATE
}

/// Serialises tests that share the process-global stub and environment.
///
/// This is deliberately a *separate* mutex from the stub state: the stub's
/// server thread needs the state mutex while a test is running, so holding it
/// for the test body would deadlock every request.
pub fn lock() -> MutexGuard<'static, ()> {
    static SERIAL: LazyLock<Mutex<()>> = LazyLock::new(|| Mutex::new(()));
    SERIAL.lock().unwrap_or_else(|e| e.into_inner())
}

// ---------------------------------------------------------------------------
// UUID discovery — the Python recorder substitutes `__FIRST_CLAIM_ID__` with
// the first UUID appearing in the human message, so the stub must do the same.
// ---------------------------------------------------------------------------

fn is_hex(b: u8) -> bool {
    b.is_ascii_digit() || (b'a'..=b'f').contains(&b)
}

fn first_uuid(text: &str) -> Option<String> {
    let bytes = text.as_bytes();
    let mut i = 0;
    while i + 36 <= bytes.len() {
        let window = &bytes[i..i + 36];
        let shaped =
            window[8] == b'-' && window[13] == b'-' && window[18] == b'-' && window[23] == b'-';
        if shaped {
            let mut ok = true;
            for (offset, byte) in window.iter().enumerate() {
                if matches!(offset, 8 | 13 | 18 | 23) {
                    continue;
                }
                if !is_hex(*byte) {
                    ok = false;
                    break;
                }
            }
            if ok {
                return Some(text[i..i + 36].to_string());
            }
        }
        i += 1;
    }
    None
}

fn substitute(value: &Value, claim_id: &str) -> Value {
    match value {
        Value::String(s) => Value::String(s.replace("__FIRST_CLAIM_ID__", claim_id)),
        Value::Array(items) => {
            Value::Array(items.iter().map(|v| substitute(v, claim_id)).collect())
        }
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(k, v)| (k.clone(), substitute(v, claim_id)))
                .collect(),
        ),
        other => other.clone(),
    }
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

fn read_request(stream: &mut TcpStream) -> Option<(String, Value)> {
    let mut reader = BufReader::new(stream.try_clone().ok()?);
    let mut request_line = String::new();
    reader.read_line(&mut request_line).ok()?;
    let path = request_line.split_whitespace().nth(1)?.to_string();

    let mut content_length = 0usize;
    loop {
        let mut header = String::new();
        if reader.read_line(&mut header).ok()? == 0 {
            break;
        }
        if header == "\r\n" || header == "\n" {
            break;
        }
        let lower = header.to_ascii_lowercase();
        if let Some(rest) = lower.strip_prefix("content-length:") {
            content_length = rest.trim().parse().unwrap_or(0);
        }
    }
    let mut body = vec![0u8; content_length];
    reader.read_exact(&mut body).ok()?;
    let parsed = serde_json::from_slice(&body).unwrap_or(Value::Null);
    Some((path, parsed))
}

fn respond(stream: &mut TcpStream, payload: &Value) {
    let body = serde_json::to_vec(payload).unwrap_or_default();
    let head = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    let _ = stream.write_all(head.as_bytes());
    let _ = stream.write_all(&body);
    let _ = stream.flush();
}

fn schema_of(body: &Value) -> String {
    if let Some(name) = body
        .pointer("/tools/0/function/name")
        .and_then(|v| v.as_str())
    {
        return name.to_string();
    }
    if let Some(name) = body
        .pointer("/response_format/json_schema/name")
        .and_then(|v| v.as_str())
    {
        return name.to_string();
    }
    String::new()
}

fn last_user_message(body: &Value) -> String {
    body.get("messages")
        .and_then(|m| m.as_array())
        .and_then(|messages| {
            messages
                .iter()
                .rev()
                .find(|m| m.get("role").and_then(|r| r.as_str()) == Some("user"))
        })
        .and_then(|m| m.get("content"))
        .and_then(|c| c.as_str())
        .unwrap_or_default()
        .to_string()
}

fn handle(path: &str, body: &Value) -> Value {
    if path.ends_with("/embeddings") {
        let inputs: Vec<String> = match body.get("input") {
            Some(Value::String(s)) => vec![s.clone()],
            Some(Value::Array(items)) => items
                .iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect(),
            _ => Vec::new(),
        };
        let data: Vec<Value> = inputs
            .iter()
            .enumerate()
            .map(|(i, text)| {
                json!({
                    "object": "embedding",
                    "index": i,
                    "embedding": hash_embed(text),
                })
            })
            .collect();
        return json!({"object": "list", "data": data, "model": "stub-embed"});
    }

    let schema = schema_of(body);
    let user = last_user_message(body);
    let mut guard = state().lock().expect("stub state");
    guard.call_order.push(schema.clone());
    guard.user_messages.push(user.clone());

    let entry = guard.script.get(guard.cursor).cloned();
    guard.cursor += 1;
    drop(guard);

    let Some(entry) = entry else {
        return json!({
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "", "tool_calls": []},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        });
    };

    let claim_id = first_uuid(&user).unwrap_or_default();
    let arguments = substitute(&entry.payload, &claim_id);
    json!({
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": arguments.to_string(),
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": entry.schema,
                        "arguments": arguments.to_string(),
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {"prompt_tokens": 42, "completion_tokens": 7},
    })
}

/// Start the stub server on an ephemeral port; returns its base URL.
pub fn spawn_server() -> String {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind stub server");
    let port = listener.local_addr().expect("stub addr").port();
    std::thread::spawn(move || {
        for inbound in listener.incoming() {
            let Ok(mut stream) = inbound else { continue };
            let Some((path, body)) = read_request(&mut stream) else {
                continue;
            };
            let response = handle(&path, &body);
            respond(&mut stream, &response);
        }
    });
    format!("http://127.0.0.1:{}", port)
}

// ---------------------------------------------------------------------------
// Environment
// ---------------------------------------------------------------------------

/// Point both providers at the stub and install fake credentials.
///
/// `base_url` is the server root without the `/v1` suffix the client appends,
/// so the stub receives `<base>/chat/completions`.
pub fn install_env(base_url: &str) {
    std::env::set_var("THINK_TANK_PROVIDER", "ollama_cloud");
    std::env::set_var("THINK_TANK_EMBEDDING_PROVIDER", "openrouter");
    std::env::set_var(
        "THINK_TANK_BASE_URL_OLLAMA_CLOUD",
        format!("{}/v1", base_url),
    );
    std::env::set_var("THINK_TANK_BASE_URL_OPENROUTER", format!("{}/v1", base_url));
    std::env::set_var("OLLAMA_CLOUD_API_KEY", "stub-chat-key");
    std::env::set_var("OPENROUTER_API_KEY", "stub-embed-key");
    for name in [
        "THINK_TANK_CHAT_MODEL",
        "THINK_TANK_MAX_TOKENS",
        "THINK_TANK_REASONING_EFFORT",
        "THINK_TANK_RESEARCHER_PROVIDER",
        "THINK_TANK_SKEPTIC_PROVIDER",
        "THINK_TANK_VISIONARY_PROVIDER",
        "THINK_TANK_SYNTHESIZER_PROVIDER",
    ] {
        std::env::remove_var(name);
    }
}

/// A temporary vector-store directory, removed on drop.
pub struct TempDir {
    pub path: std::path::PathBuf,
}

impl TempDir {
    pub fn new(label: &str) -> Self {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let path = std::env::temp_dir().join(format!("think-tank-{}-{}", label, unique));
        std::fs::create_dir_all(&path).expect("temp dir");
        TempDir { path }
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

// ---------------------------------------------------------------------------
// Fixture loading
// ---------------------------------------------------------------------------

pub fn load_fixtures() -> Value {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/python_golden.json");
    let raw = std::fs::read_to_string(path).expect("read python_golden.json");
    serde_json::from_str(&raw).expect("parse python_golden.json")
}

pub fn fixture_scenarios() -> Vec<Value> {
    load_fixtures()
        .get("scenarios")
        .and_then(|s| s.as_array())
        .cloned()
        .unwrap_or_default()
}

pub fn script_for(scenario: &Value) -> Vec<ScriptEntry> {
    scenario
        .get("script")
        .and_then(|s| s.as_array())
        .map(|entries| {
            entries
                .iter()
                .map(|entry| ScriptEntry {
                    schema: entry
                        .get("schema")
                        .and_then(|s| s.as_str())
                        .unwrap_or_default()
                        .to_string(),
                    payload: entry.get("payload").cloned().unwrap_or(Value::Null),
                })
                .collect()
        })
        .unwrap_or_default()
}

pub fn install_script(entries: Vec<ScriptEntry>) {
    let mut guard = state().lock().expect("stub state");
    guard.script = entries;
    guard.cursor = 0;
    guard.call_order.clear();
    guard.user_messages.clear();
}

pub fn call_order() -> Vec<String> {
    state().lock().expect("stub state").call_order.clone()
}

pub fn call_count() -> usize {
    state().lock().expect("stub state").cursor
}

// ---------------------------------------------------------------------------
// Normalisation — mirrors `normalise()` in record_python_golden.py
// ---------------------------------------------------------------------------

/// Assign stable tokens in first-appearance order, exactly as the recorder does.
pub fn id_tokens(
    claims: &[Value],
    challenges: &[Value],
    expansions: &[Value],
    syntheses: &[Value],
    expansion: Option<&Value>,
    synthesis: Option<&Value>,
) -> Vec<(String, String)> {
    let mut order: Vec<String> = Vec::new();
    let mut push = |id: Option<&str>| {
        if let Some(id) = id {
            if !id.is_empty() && !order.iter().any(|existing| existing == id) {
                order.push(id.to_string());
            }
        }
    };
    for item in claims
        .iter()
        .chain(challenges)
        .chain(expansions)
        .chain(syntheses)
    {
        push(item.get("id").and_then(|v| v.as_str()));
    }
    if let Some(value) = expansion {
        push(value.get("id").and_then(|v| v.as_str()));
    }
    if let Some(value) = synthesis {
        push(value.get("id").and_then(|v| v.as_str()));
    }
    order
        .into_iter()
        .enumerate()
        .map(|(index, id)| (id, format!("{:08x}-0000-4000-8000-000000000000", index + 1)))
        .collect()
}

/// Replace generated ids and timestamps with stable tokens.
pub fn normalise(value: &Value, tokens: &[(String, String)]) -> Value {
    match value {
        Value::String(s) => {
            let mut out = s.clone();
            for (id, token) in tokens {
                out = out.replace(id.as_str(), token.as_str());
            }
            for (id, token) in tokens {
                let id_prefix: String = id.chars().take(8).collect();
                let token_prefix: String = token.chars().take(8).collect();
                out = out.replace(&id_prefix, &token_prefix);
            }
            Value::String(out)
        }
        Value::Array(items) => Value::Array(items.iter().map(|v| normalise(v, tokens)).collect()),
        Value::Object(map) => {
            let mut out = serde_json::Map::new();
            for (key, raw) in map {
                if key == "created_at" {
                    out.insert(key.clone(), Value::String("<timestamp>".into()));
                } else if key == "id" {
                    let replaced = raw
                        .as_str()
                        .and_then(|id| tokens.iter().find(|(k, _)| k == id))
                        .map(|(_, token)| Value::String(token.clone()))
                        .unwrap_or_else(|| raw.clone());
                    out.insert(key.clone(), replaced);
                } else {
                    out.insert(key.clone(), normalise(raw, tokens));
                }
            }
            Value::Object(out)
        }
        other => other.clone(),
    }
}
