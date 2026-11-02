//! Provider-agnostic chat and embedding clients, mirroring `think_tank/llm.py`.
//!
//! Every supported provider speaks the OpenAI chat-completions protocol, so a
//! single HTTP client with a per-provider `base_url` covers all of them.
//! Credentials are read from the process environment; no `.env` file is loaded.
//!
//! Chat selection precedence:
//!     per-agent config -> `THINK_TANK_<AGENT>_PROVIDER` -> `THINK_TANK_PROVIDER`
//!     -> `DEFAULT_CHAT_PROVIDER`
//! and, independently:
//!     per-agent config -> `THINK_TANK_<AGENT>_MODEL` -> `THINK_TANK_CHAT_MODEL`
//!     -> provider default model
//!
//! Embedding selection precedence:
//!     `THINK_TANK_EMBEDDING_PROVIDER` -> `DEFAULT_EMBEDDING_PROVIDER`

use std::time::Duration;

use serde_json::{json, Value};

use crate::schemas::{parse_output, SchemaKind};
use crate::telemetry::recorder;

pub const DEFAULT_CHAT_PROVIDER: &str = "ollama_cloud";
pub const DEFAULT_EMBEDDING_PROVIDER: &str = "openrouter";
pub const DEFAULT_CHAT_MODEL: &str = "deepseek-v4.1-flash";
pub const AGENT_NAMES: [&str; 4] = ["researcher", "skeptic", "visionary", "synthesizer"];

/// Runaway guard, not a length control.
pub const DEFAULT_MAX_TOKENS: u32 = 4096;

pub const STRUCTURED_RETRIES: u32 = 3;

/// Which structured-output mechanism a provider supports.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StructuredMethod {
    FunctionCalling,
    JsonMode,
    JsonSchema,
}

/// An OpenAI-compatible inference endpoint.
#[derive(Debug, Clone, Copy)]
pub struct Provider {
    pub name: &'static str,
    pub api_key_env: &'static str,
    pub base_url: &'static str,
    pub default_model: &'static str,
    pub supports_chat: bool,
    pub embeddings_model: Option<&'static str>,
    pub structured_output_method: StructuredMethod,
    /// Sent only when set: most providers reject the parameter outright.
    pub reasoning_effort: Option<&'static str>,
    pub headers: &'static [(&'static str, &'static str)],
}

impl Provider {
    /// The configured key, or `None` when the variable is unset/empty.
    pub fn api_key(&self) -> Option<String> {
        std::env::var(self.api_key_env)
            .ok()
            .filter(|v| !v.is_empty())
    }

    pub fn supports_embeddings(&self) -> bool {
        self.embeddings_model.is_some()
    }

    /// `default_headers()`, resolved per call so env changes take effect.
    pub fn default_headers(&self) -> Vec<(String, String)> {
        self.headers
            .iter()
            .filter_map(|(key, env)| {
                std::env::var(env)
                    .ok()
                    .filter(|v| !v.is_empty())
                    .map(|v| (key.to_string(), v))
            })
            .collect()
    }

    /// Base URL for requests. `THINK_TANK_BASE_URL_<PROVIDER>` redirects one
    /// provider at a local stub server (used by the integration tests).
    pub fn resolved_base_url(&self) -> String {
        let env_name = format!("THINK_TANK_BASE_URL_{}", self.name.to_uppercase());
        std::env::var(env_name)
            .ok()
            .filter(|v| !v.is_empty())
            .unwrap_or_else(|| self.base_url.to_string())
    }
}

pub static PROVIDERS: &[Provider] = &[
    Provider {
        name: "ollama_cloud",
        api_key_env: "OLLAMA_CLOUD_API_KEY",
        base_url: "https://ollama.com/v1",
        default_model: DEFAULT_CHAT_MODEL,
        supports_chat: true,
        embeddings_model: None,
        structured_output_method: StructuredMethod::FunctionCalling,
        reasoning_effort: Some("none"),
        headers: &[],
    },
    Provider {
        name: "mistral",
        api_key_env: "MISTRAL_API_KEY",
        base_url: "https://api.mistral.ai/v1",
        default_model: "mistral-small-latest",
        supports_chat: true,
        embeddings_model: Some("mistral-embed"),
        structured_output_method: StructuredMethod::JsonSchema,
        reasoning_effort: None,
        headers: &[],
    },
    Provider {
        name: "opencode",
        api_key_env: "OPENCODE_API_KEY",
        base_url: "https://opencode.ai/zen/v1",
        default_model: DEFAULT_CHAT_MODEL,
        supports_chat: true,
        embeddings_model: None,
        structured_output_method: StructuredMethod::FunctionCalling,
        reasoning_effort: None,
        headers: &[],
    },
    Provider {
        name: "zai",
        api_key_env: "ZAI_API_KEY",
        base_url: "https://api.z.ai/api/paas/v4",
        default_model: "glm-5.3",
        supports_chat: true,
        embeddings_model: None,
        structured_output_method: StructuredMethod::FunctionCalling,
        reasoning_effort: None,
        headers: &[],
    },
    Provider {
        name: "openrouter",
        api_key_env: "OPENROUTER_API_KEY",
        base_url: "https://openrouter.ai/api/v1",
        default_model: DEFAULT_CHAT_MODEL,
        supports_chat: false,
        embeddings_model: Some("openai/text-embedding-3-small"),
        structured_output_method: StructuredMethod::JsonSchema,
        reasoning_effort: None,
        headers: &[
            ("HTTP-Referer", "OPENROUTER_APP_URL"),
            ("X-Title", "OPENROUTER_APP_TITLE"),
        ],
    },
];

pub fn provider_names() -> Vec<&'static str> {
    let mut names: Vec<&'static str> = PROVIDERS.iter().map(|p| p.name).collect();
    names.sort_unstable();
    names
}

/// Resolve a provider by name, falling back to `THINK_TANK_PROVIDER`.
pub fn resolve_provider(name: Option<&str>, for_chat: bool) -> Result<&'static Provider, String> {
    let resolved = match name {
        Some(n) if !n.trim().is_empty() => n.trim().to_lowercase(),
        _ => {
            let env_name = if for_chat {
                "THINK_TANK_PROVIDER"
            } else {
                "THINK_TANK_EMBEDDING_PROVIDER"
            };
            let fallback = if for_chat {
                DEFAULT_CHAT_PROVIDER
            } else {
                DEFAULT_EMBEDDING_PROVIDER
            };
            std::env::var(env_name)
                .ok()
                .filter(|v| !v.is_empty())
                .unwrap_or_else(|| fallback.to_string())
                .trim()
                .to_lowercase()
        }
    };
    let provider = PROVIDERS
        .iter()
        .find(|p| p.name == resolved)
        .ok_or_else(|| {
            format!(
                "Unknown provider {:?}. Choose one of: {}.",
                resolved,
                provider_names().join(", ")
            )
        })?;
    if for_chat && !provider.supports_chat {
        let chat_names: Vec<&str> = PROVIDERS
            .iter()
            .filter(|p| p.supports_chat)
            .map(|p| p.name)
            .collect();
        return Err(format!(
            "Provider {:?} is reserved for embeddings and judge models, not chat. Use one of: {}.",
            resolved,
            chat_names.join(", ")
        ));
    }
    Ok(provider)
}

fn api_key(provider: &Provider) -> Result<String, String> {
    provider.api_key().ok_or_else(|| {
        format!(
            "{} is not set. Export it before running (e.g. in ~/.zshenv) or pick a \
             provider whose key you do have.",
            provider.api_key_env
        )
    })
}

fn int_env(name: &str, default: u32) -> u32 {
    match std::env::var(name) {
        Ok(raw) if !raw.is_empty() => raw.parse().unwrap_or(default),
        _ => default,
    }
}

/// Reasoning effort to send, or `None` to omit the parameter entirely.
fn effort_for(provider: &Provider) -> Option<String> {
    provider.reasoning_effort?;
    std::env::var("THINK_TANK_REASONING_EFFORT")
        .ok()
        .filter(|v| !v.is_empty())
        .or_else(|| provider.reasoning_effort.map(|e| e.to_string()))
}

/// Per-agent chat client settings.
#[derive(Debug, Clone, Default)]
pub struct ChatSpec {
    pub provider: Option<String>,
    pub model: Option<String>,
    pub max_tokens: Option<u32>,
    pub reasoning_effort: Option<String>,
    pub temperature: f64,
}

fn agent_provider_name(agent: &str, config: &crate::runner::Config) -> Option<String> {
    config
        .agent_provider(agent)
        .map(|s| s.to_string())
        .or_else(|| {
            std::env::var(format!("THINK_TANK_{}_PROVIDER", agent.to_uppercase()))
                .ok()
                .filter(|v| !v.is_empty())
        })
}

/// Build the chat spec honouring per-agent provider/model overrides.
///
/// A global `THINK_TANK_CHAT_MODEL` belongs to the global provider, so it is
/// not applied to an agent whose provider was overridden — that pairing would
/// send a model name the other endpoint does not serve.
pub fn agent_chat_spec(
    agent: &str,
    config: &crate::runner::Config,
    temperature: f64,
) -> Result<(ChatSpec, &'static Provider), String> {
    let upper = agent.to_uppercase();
    let name = agent_provider_name(agent, config);
    let mut model = config
        .agent_model(agent)
        .map(|s| s.to_string())
        .or_else(|| {
            std::env::var(format!("THINK_TANK_{}_MODEL", upper))
                .ok()
                .filter(|v| !v.is_empty())
        });
    if name.is_some() && model.is_none() {
        model = Some(
            resolve_provider(name.as_deref(), true)?
                .default_model
                .to_string(),
        );
    }
    let provider = resolve_provider(name.as_deref(), true)?;
    let max_tokens = config.agent_max_tokens(agent).or_else(|| {
        std::env::var(format!("THINK_TANK_{}_MAX_TOKENS", upper))
            .ok()
            .and_then(|v| v.parse().ok())
    });
    let reasoning_effort = config
        .agent_reasoning_effort(agent)
        .map(|s| s.to_string())
        .or_else(|| {
            std::env::var(format!("THINK_TANK_{}_REASONING_EFFORT", upper))
                .ok()
                .filter(|v| !v.is_empty())
        });
    Ok((
        ChatSpec {
            provider: name,
            model,
            max_tokens,
            reasoning_effort,
            temperature,
        },
        provider,
    ))
}

/// The model name a spec resolves to, after every env fallback.
fn resolved_model(spec: &ChatSpec, provider: &Provider) -> String {
    spec.model
        .clone()
        .or_else(|| {
            std::env::var("THINK_TANK_CHAT_MODEL")
                .ok()
                .filter(|v| !v.is_empty())
        })
        .unwrap_or_else(|| provider.default_model.to_string())
}

fn http_agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(30))
        .timeout_read(Duration::from_secs(600))
        .timeout_write(Duration::from_secs(120))
        .build()
}

fn post_json(
    url: &str,
    key: &str,
    headers: &[(String, String)],
    body: &Value,
) -> Result<Value, String> {
    let agent = http_agent();
    let mut request = agent
        .post(url)
        .set("Content-Type", "application/json")
        .set("Authorization", &format!("Bearer {}", key));
    for (name, value) in headers {
        request = request.set(name, value);
    }
    let response = match request.send_json(body.clone()) {
        Ok(r) => r,
        Err(ureq::Error::Status(code, r)) => {
            let text = r.into_string().unwrap_or_default();
            return Err(format!("HTTP {} from {}: {}", code, url, text));
        }
        Err(e) => return Err(format!("request to {} failed: {}", url, e)),
    };
    response
        .into_json::<Value>()
        .map_err(|e| format!("invalid JSON from {}: {}", url, e))
}

/// One raw chat completion.
struct ChatResponse {
    content: String,
    tool_arguments: Option<String>,
    had_tool_calls: bool,
    input_tokens: Option<u64>,
    output_tokens: Option<u64>,
}

fn chat_completion(
    provider: &Provider,
    model: &str,
    key: &str,
    spec: &ChatSpec,
    messages: &[(&'static str, String)],
    schema: Option<SchemaKind>,
) -> Result<ChatResponse, String> {
    let token_cap = spec
        .max_tokens
        .unwrap_or_else(|| int_env("THINK_TANK_MAX_TOKENS", DEFAULT_MAX_TOKENS));
    let mut body = json!({
        "model": model,
        "messages": messages
            .iter()
            .map(|(role, content)| json!({"role": role, "content": content}))
            .collect::<Vec<_>>(),
        "temperature": spec.temperature,
        "max_tokens": token_cap,
    });
    let effort = spec
        .reasoning_effort
        .clone()
        .or_else(|| effort_for(provider));
    if let Some(effort) = effort {
        body["reasoning_effort"] = json!(effort);
    }
    if let Some(kind) = schema {
        let schema_json = kind.json_schema();
        match provider.structured_output_method {
            StructuredMethod::FunctionCalling => {
                body["tools"] = json!([{
                    "type": "function",
                    "function": {
                        "name": kind.name(),
                        "description": format!("Return a structured {}.", kind.name()),
                        "parameters": schema_json,
                    }
                }]);
                body["tool_choice"] = json!({
                    "type": "function",
                    "function": {"name": kind.name()}
                });
            }
            StructuredMethod::JsonSchema => {
                body["response_format"] = json!({
                    "type": "json_schema",
                    "json_schema": {
                        "name": kind.name(),
                        "schema": schema_json,
                        "strict": true,
                    }
                });
            }
            StructuredMethod::JsonMode => {
                body["response_format"] = json!({"type": "json_object"});
            }
        }
    }

    let url = format!(
        "{}/chat/completions",
        provider.resolved_base_url().trim_end_matches('/')
    );
    let response = post_json(&url, key, &provider.default_headers(), &body)?;

    let choice = response
        .get("choices")
        .and_then(|c| c.as_array())
        .and_then(|c| c.first())
        .ok_or_else(|| "response had no choices".to_string())?;
    let message = choice
        .get("message")
        .ok_or_else(|| "response choice had no message".to_string())?;
    let content = message
        .get("content")
        .and_then(|c| c.as_str())
        .unwrap_or_default()
        .to_string();
    let tool_calls = message.get("tool_calls").and_then(|c| c.as_array());
    let had_tool_calls = tool_calls.map(|c| !c.is_empty()).unwrap_or(false);
    let tool_arguments = tool_calls
        .and_then(|calls| calls.first())
        .and_then(|call| call.get("function"))
        .and_then(|f| f.get("arguments"))
        .and_then(|a| a.as_str())
        .map(|s| s.to_string());
    let usage = response.get("usage");
    Ok(ChatResponse {
        content,
        tool_arguments,
        had_tool_calls,
        input_tokens: usage
            .and_then(|u| u.get("prompt_tokens"))
            .and_then(|v| v.as_u64()),
        output_tokens: usage
            .and_then(|u| u.get("completion_tokens"))
            .and_then(|v| v.as_u64()),
    })
}

/// Call one agent's structured LLM, retrying weak tool-call emissions.
///
/// Smaller models occasionally return a tool call with empty or malformed
/// arguments; those turns are retried instead of failing the node.
pub fn invoke_structured(
    agent: &str,
    config: &crate::runner::Config,
    kind: SchemaKind,
    system: &str,
    user: &str,
    temperature: f64,
) -> Result<Value, String> {
    let (spec, provider) = agent_chat_spec(agent, config, temperature)?;
    let model = resolved_model(&spec, provider);
    let key = api_key(provider)?;
    let messages = [("system", system.to_string()), ("user", user.to_string())];
    let chars: usize = messages.iter().map(|(_, m)| m.chars().count()).sum();
    let mut last_error = String::from("no attempt made");

    for attempt in 1..=STRUCTURED_RETRIES {
        let outcome = recorder().span(&format!("{}.llm", agent), "llm", |span| {
            let mut span = span;
            if let Some(inner) = span.as_mut() {
                inner
                    .attrs
                    .push(("provider".into(), provider.name.to_string()));
                inner.attrs.push(("model".into(), model.clone()));
                inner.attrs.push(("attempt".into(), attempt.to_string()));
            }
            let response = chat_completion(provider, &model, &key, &spec, &messages, Some(kind));
            if let Some(inner) = span.as_mut() {
                if let Ok(response) = &response {
                    inner.attrs.push((
                        "in_tok".into(),
                        response
                            .input_tokens
                            .map(|v| v.to_string())
                            .unwrap_or_default(),
                    ));
                    inner.attrs.push((
                        "out_tok".into(),
                        response
                            .output_tokens
                            .map(|v| v.to_string())
                            .unwrap_or_default(),
                    ));
                }
                inner.attrs.push(("chars".into(), chars.to_string()));
            }
            response
        });

        let response = outcome?;
        let payload: Option<Value> = match (&response.tool_arguments, kind) {
            (Some(args), _) if !args.trim().is_empty() => serde_json::from_str(args).ok(),
            (_, SchemaKind::Researcher) | (_, SchemaKind::Synthesizer) => {
                serde_json::from_str::<Value>(&response.content).ok()
            }
            _ => serde_json::from_str::<Value>(&response.content).ok(),
        };
        if let Some(payload) = payload {
            match parse_output(kind, &payload) {
                Ok(valid) => return Ok(valid),
                Err(err) => last_error = err,
            }
        } else {
            last_error = if response.had_tool_calls {
                "tool call arguments were not valid JSON".to_string()
            } else {
                "model returned no tool call".to_string()
            };
        }
    }
    Err(format!(
        "{} model did not return valid {} after {} attempts: {}",
        agent,
        kind.name(),
        STRUCTURED_RETRIES,
        last_error
    ))
}

/// Resolve the embedding provider, rejecting providers without embeddings.
pub fn resolve_embedding_provider(name: Option<&str>) -> Result<&'static Provider, String> {
    let provider = resolve_provider(name, false)?;
    if !provider.supports_embeddings() {
        let names: Vec<&str> = PROVIDERS
            .iter()
            .filter(|p| p.supports_embeddings())
            .map(|p| p.name)
            .collect();
        return Err(format!(
            "Provider {:?} does not serve embeddings. Set THINK_TANK_EMBEDDING_PROVIDER \
             to one of: {}.",
            provider.name,
            names.join(", ")
        ));
    }
    Ok(provider)
}

/// The embedding model in effect for the resolved provider.
pub fn embedding_model(provider: &Provider, model: Option<&str>) -> String {
    model
        .map(|s| s.to_string())
        .or_else(|| {
            std::env::var("THINK_TANK_EMBEDDING_MODEL")
                .ok()
                .filter(|v| !v.is_empty())
        })
        .or_else(|| provider.embeddings_model.map(|s| s.to_string()))
        .unwrap_or_default()
}

fn embed_batch(
    provider: &Provider,
    model: &str,
    texts: &[String],
) -> Result<Vec<Vec<f64>>, String> {
    let key = api_key(provider)?;
    let url = format!(
        "{}/embeddings",
        provider.resolved_base_url().trim_end_matches('/')
    );
    let body = json!({"model": model, "input": texts});
    let response = post_json(&url, &key, &provider.default_headers(), &body)?;
    let data = response
        .get("data")
        .and_then(|d| d.as_array())
        .ok_or_else(|| "embedding response had no data".to_string())?;
    let mut out = Vec::with_capacity(data.len());
    for item in data {
        let embedding = item
            .get("embedding")
            .and_then(|e| e.as_array())
            .ok_or_else(|| "embedding item had no vector".to_string())?;
        out.push(
            embedding
                .iter()
                .filter_map(|v| v.as_f64())
                .collect::<Vec<f64>>(),
        );
    }
    Ok(out)
}

/// Embed a batch of documents, recording one span per batch.
pub fn embed_documents(
    provider: &Provider,
    model: &str,
    texts: &[String],
) -> Result<Vec<Vec<f64>>, String> {
    recorder().mark(
        "embeddings.documents",
        "embedding",
        &[
            ("provider", provider.name.to_string()),
            ("model", model.to_string()),
            ("n", texts.len().to_string()),
        ],
        || embed_batch(provider, model, texts),
    )
}

/// Embed one query. Delegates to the same endpoint as `embed_documents`, and
/// is not given its own span so the call is not double-counted.
pub fn embed_query(text: &str) -> Result<Vec<f64>, String> {
    let provider = resolve_embedding_provider(None)?;
    let model = embedding_model(provider, None);
    let mut vectors = embed_batch(provider, &model, &[text.to_string()])?;
    vectors
        .pop()
        .ok_or_else(|| "embedding response was empty".to_string())
}

/// Chroma collection scoped to the embedding space.
pub fn embedding_collection_name(
    provider: Option<&str>,
    model: Option<&str>,
) -> Result<String, String> {
    let p = resolve_embedding_provider(provider)?;
    let resolved_model = embedding_model(p, model);
    let raw = format!("{}-{}", p.name, resolved_model).to_lowercase();
    let slug: String = raw
        .chars()
        .map(|c| {
            if c.is_ascii_lowercase() || c.is_ascii_digit() {
                c
            } else {
                '-'
            }
        })
        .collect();
    let slug = slug.trim_matches('-').to_string();
    let collapsed = collapse_dashes(&slug);
    Ok(format!("think_tank_kb__{}", collapsed))
}

fn collapse_dashes(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut last_dash = false;
    for c in s.chars() {
        if c == '-' {
            if !last_dash {
                out.push(c);
            }
            last_dash = true;
        } else {
            out.push(c);
            last_dash = false;
        }
    }
    out
}

/// Environment variables required by the configured chat and embedding providers.
pub fn missing_credentials() -> Result<Vec<String>, String> {
    let mut required = vec![resolve_provider(None, true)?.api_key_env];
    let embedding = resolve_embedding_provider(None)?;
    if !required.contains(&embedding.api_key_env) {
        required.push(embedding.api_key_env);
    }
    for agent in AGENT_NAMES {
        if let Ok(override_name) =
            std::env::var(format!("THINK_TANK_{}_PROVIDER", agent.to_uppercase()))
        {
            if !override_name.is_empty() {
                let env_name = resolve_provider(Some(&override_name), true)?.api_key_env;
                if !required.contains(&env_name) {
                    required.push(env_name);
                }
            }
        }
    }
    Ok(required
        .into_iter()
        .filter(|name| std::env::var(name).map(|v| v.is_empty()).unwrap_or(true))
        .map(|name| name.to_string())
        .collect())
}
