//! Ported coverage for the rules AGENTS.md calls "easy to break".
//!
//! These cases come from the deleted `tests/test_llm.py` and
//! `tests/test_schemas.py`. The Python tree no longer exists, so this file is
//! the only place those invariants are pinned.

mod support;

use serde_json::json;
use think_tank::llm::{
    embedding_collection_name, missing_credentials, resolve_embedding_provider,
    resolve_provider as resolve, AGENT_NAMES, DEFAULT_CHAT_MODEL, DEFAULT_CHAT_PROVIDER,
    DEFAULT_EMBEDDING_PROVIDER, PROVIDERS, STRUCTURED_RETRIES,
};
use think_tank::runner::Config;
use think_tank::schemas::{parse_output, stringify_dimensions, Confidence, SchemaKind, Stance};

/// Clear every variable that changes provider/model resolution.
fn sweep_env() {
    let mut names: Vec<String> = vec![
        "THINK_TANK_PROVIDER".into(),
        "THINK_TANK_CHAT_MODEL".into(),
        "THINK_TANK_EMBEDDING_PROVIDER".into(),
        "THINK_TANK_EMBEDDING_MODEL".into(),
        "THINK_TANK_REASONING_EFFORT".into(),
        "THINK_TANK_MAX_TOKENS".into(),
        "THINK_TANK_KB_PATH".into(),
    ];
    for agent in AGENT_NAMES {
        for suffix in ["PROVIDER", "MODEL", "MAX_TOKENS", "REASONING_EFFORT"] {
            names.push(format!("THINK_TANK_{}_{}", agent.to_uppercase(), suffix));
        }
    }
    for name in names {
        std::env::remove_var(name);
    }
}

fn with_keys() {
    for (name, value) in [
        ("OPENROUTER_API_KEY", "sk-or-test"),
        ("OLLAMA_CLOUD_API_KEY", "ollama-test"),
        ("MISTRAL_API_KEY", "mistral-test"),
        ("ZAI_API_KEY", "zai-test"),
        ("OPENCODE_API_KEY", "opencode-test"),
    ] {
        std::env::set_var(name, value);
    }
}

/// Every env-mutating test holds this serialisation guard for its whole body.
fn clean_env() -> std::sync::MutexGuard<'static, ()> {
    let guard = support::lock();
    sweep_env();
    with_keys();
    guard
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

#[test]
fn every_provider_is_openai_compatible() {
    let _guard = support::lock();
    for provider in PROVIDERS {
        assert!(
            provider.base_url.starts_with("https://"),
            "{} base_url",
            provider.name
        );
        assert!(
            provider.api_key_env.ends_with("_API_KEY"),
            "{} key var",
            provider.name
        );
        assert!(
            !provider.default_model.is_empty(),
            "{} model",
            provider.name
        );
    }
}

#[test]
fn openrouter_is_embeddings_only() {
    let _guard = support::lock();
    let openrouter = PROVIDERS.iter().find(|p| p.name == "openrouter").unwrap();
    assert!(!openrouter.supports_chat);
    assert!(openrouter.supports_embeddings());
}

#[test]
fn defaults_and_serving_sets_are_fixed() {
    let _guard = support::lock();
    assert_eq!(DEFAULT_CHAT_PROVIDER, "ollama_cloud");
    assert_eq!(DEFAULT_EMBEDDING_PROVIDER, "openrouter");
    assert_eq!(DEFAULT_CHAT_MODEL, "deepseek-v4.1-flash");

    let mut serving: Vec<&str> = PROVIDERS
        .iter()
        .filter(|p| p.supports_embeddings())
        .map(|p| p.name)
        .collect();
    serving.sort_unstable();
    assert_eq!(serving, vec!["mistral", "openrouter"]);

    for name in ["ollama_cloud", "opencode"] {
        let p = PROVIDERS.iter().find(|p| p.name == name).unwrap();
        assert_eq!(p.default_model, "deepseek-v4.1-flash");
    }
    assert_eq!(
        PROVIDERS
            .iter()
            .find(|p| p.name == "mistral")
            .unwrap()
            .default_model,
        "mistral-small-latest"
    );
}

// ---------------------------------------------------------------------------
// Provider resolution
// ---------------------------------------------------------------------------

#[test]
fn resolve_provider_defaults_to_ollama_cloud() {
    let _g = clean_env();
    assert_eq!(resolve(None, true).unwrap().name, "ollama_cloud");
}

#[test]
fn resolve_provider_rejects_openrouter_for_chat() {
    let _g = clean_env();
    let error = resolve(Some("openrouter"), true).unwrap_err();
    assert!(
        error.contains("reserved for embeddings"),
        "unexpected error: {error}"
    );
    // ... but accepts it for embeddings.
    assert_eq!(
        resolve(Some("openrouter"), false).unwrap().name,
        "openrouter"
    );
}

#[test]
fn openrouter_is_rejected_when_selected_through_env() {
    let _g = clean_env();
    std::env::set_var("THINK_TANK_PROVIDER", "openrouter");
    assert!(resolve_reserved_error());
}

fn resolve_reserved_error() -> bool {
    resolve(None, true)
        .map(|_| false)
        .unwrap_or_else(|e| e.contains("reserved for embeddings"))
}

#[test]
fn env_selects_provider_but_explicit_argument_wins() {
    let _g = clean_env();
    std::env::set_var("THINK_TANK_PROVIDER", "mistral");
    assert_eq!(resolve(None, true).unwrap().name, "mistral");
    assert_eq!(resolve(Some("zai"), true).unwrap().name, "zai");
}

#[test]
fn provider_name_is_case_and_space_insensitive() {
    let _g = clean_env();
    assert_eq!(resolve(Some("  MISTRAL "), true).unwrap().name, "mistral");
}

#[test]
fn unknown_provider_lists_alternatives() {
    let _g = clean_env();
    let error = resolve(Some("nope"), true).unwrap_err();
    assert!(error.contains("openrouter"), "error: {error}");
    assert!(error.contains("Unknown provider"), "error: {error}");
}

// ---------------------------------------------------------------------------
// Per-agent precedence
// ---------------------------------------------------------------------------

#[test]
fn per_agent_config_overrides_provider_and_model() {
    let _g = clean_env();
    let config = Config::new().with_overrides(&std::collections::BTreeMap::from([
        ("visionary_provider".to_string(), "zai".to_string()),
        ("visionary_model".to_string(), "glm-5.3-flash".to_string()),
    ]));
    let (spec, provider) = think_tank::llm::agent_chat_spec("visionary", &config, 0.0).unwrap();
    assert_eq!(provider.name, "zai");
    assert_eq!(spec.model.as_deref(), Some("glm-5.3-flash"));
}

#[test]
fn per_agent_env_overrides_apply_only_to_that_agent() {
    let _g = clean_env();
    std::env::set_var("THINK_TANK_RESEARCHER_PROVIDER", "mistral");
    std::env::set_var("THINK_TANK_RESEARCHER_MODEL", "mistral-large-latest");
    let config = Config::new();

    let (spec, provider) = think_tank::llm::agent_chat_spec("researcher", &config, 0.0).unwrap();
    assert_eq!(provider.name, "mistral");
    assert_eq!(spec.model.as_deref(), Some("mistral-large-latest"));

    let (skeptic_spec, skeptic_provider) =
        think_tank::llm::agent_chat_spec("skeptic", &config, 0.0).unwrap();
    assert_eq!(skeptic_provider.name, "ollama_cloud");
    assert_eq!(skeptic_spec.model, None);
}

#[test]
fn overridden_provider_ignores_the_global_chat_model() {
    let _g = clean_env();
    // A global THINK_TANK_CHAT_MODEL belongs to the global provider; sending it
    // to an overridden endpoint would name a model that endpoint does not serve.
    std::env::set_var("THINK_TANK_CHAT_MODEL", "openai/gpt-5.4-mini");
    std::env::set_var("THINK_TANK_SKEPTIC_PROVIDER", "mistral");
    let (spec, provider) =
        think_tank::llm::agent_chat_spec("skeptic", &Config::new(), 0.0).unwrap();
    assert_eq!(provider.name, "mistral");
    assert_eq!(
        spec.model.as_deref(),
        Some("mistral-small-latest"),
        "an overridden provider falls back to its own default model"
    );
}

#[test]
fn openrouter_chat_override_is_rejected() {
    let _g = clean_env();
    std::env::set_var("THINK_TANK_SKEPTIC_PROVIDER", "openrouter");
    let error = think_tank::llm::agent_chat_spec("skeptic", &Config::new(), 0.0).unwrap_err();
    assert!(error.contains("reserved for embeddings"), "error: {error}");
}

#[test]
fn reasoning_effort_is_opt_in_per_provider() {
    let _guard = support::lock();
    // Mistral rejects the parameter outright, so it must never carry it.
    let mistral = PROVIDERS.iter().find(|p| p.name == "mistral").unwrap();
    assert_eq!(mistral.reasoning_effort, None);
    let ollama = PROVIDERS.iter().find(|p| p.name == "ollama_cloud").unwrap();
    assert_eq!(ollama.reasoning_effort, Some("none"));
}

// ---------------------------------------------------------------------------
// Embeddings
// ---------------------------------------------------------------------------

#[test]
fn embeddings_resolve_independently_of_chat() {
    let _g = clean_env();
    assert_eq!(resolve_embedding_provider(None).unwrap().name, "openrouter");
    std::env::set_var("THINK_TANK_PROVIDER", "mistral");
    assert_eq!(
        resolve_embedding_provider(None).unwrap().name,
        "openrouter",
        "chat provider selection must not move the embedding provider"
    );
}

#[test]
fn provider_without_embeddings_is_rejected() {
    let _g = clean_env();
    let error = resolve_embedding_provider(Some("zai")).unwrap_err();
    assert!(
        error.contains("does not serve embeddings"),
        "error: {error}"
    );
}

#[test]
fn collection_name_tracks_provider_and_model() {
    let _g = clean_env();
    assert_eq!(
        embedding_collection_name(None, None).unwrap(),
        "think_tank_kb__openrouter-openai-text-embedding-3-small"
    );
    assert_eq!(
        embedding_collection_name(Some("mistral"), None).unwrap(),
        "think_tank_kb__mistral-mistral-embed"
    );
    std::env::set_var("THINK_TANK_EMBEDDING_MODEL", "Some/Weird:Model v2");
    assert!(embedding_collection_name(None, None)
        .unwrap()
        .ends_with("__openrouter-some-weird-model-v2"));
}

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

#[test]
fn missing_credentials_is_empty_when_keys_are_present() {
    let _g = clean_env();
    assert!(missing_credentials().unwrap().is_empty());
}

#[test]
fn missing_credentials_names_each_required_variable() {
    let _g = clean_env();
    std::env::remove_var("OLLAMA_CLOUD_API_KEY");
    std::env::remove_var("OPENROUTER_API_KEY");
    assert_eq!(
        missing_credentials().unwrap(),
        vec![
            "OLLAMA_CLOUD_API_KEY".to_string(),
            "OPENROUTER_API_KEY".to_string()
        ]
    );
}

#[test]
fn missing_credentials_includes_per_agent_override_keys_without_duplicates() {
    let _g = clean_env();
    std::env::remove_var("ZAI_API_KEY");
    std::env::set_var("THINK_TANK_VISIONARY_PROVIDER", "zai");
    assert_eq!(
        missing_credentials().unwrap(),
        vec!["ZAI_API_KEY".to_string()]
    );

    // An override onto the already-required provider adds nothing.
    sweep_env();
    with_keys();
    std::env::set_var("THINK_TANK_SKEPTIC_PROVIDER", "ollama_cloud");
    assert!(missing_credentials().unwrap().is_empty());
}

// ---------------------------------------------------------------------------
// Structured retry budget
// ---------------------------------------------------------------------------

#[test]
fn structured_retry_budget_matches_the_documented_three() {
    assert_eq!(STRUCTURED_RETRIES, 3);
}

#[test]
fn empty_tool_call_arguments_are_retried_then_surface_a_clear_error() {
    let _guard = support::lock();
    let base_url = support::spawn_server();
    let dir = support::TempDir::new("retry");
    std::env::set_var("THINK_TANK_KB_PATH", dir.path.to_str().unwrap());
    support::install_env(&base_url);
    // No script entries: the stub answers every call with an empty tool call.
    support::install_script(Vec::new());

    let error = think_tank::llm::invoke_structured(
        "skeptic",
        &Config::new(),
        SchemaKind::Skeptic,
        "system",
        "user",
        "0.3".parse().unwrap(),
    )
    .unwrap_err();

    assert!(
        error.contains("after 3 attempts"),
        "must exhaust the retry budget: {error}"
    );
    assert_eq!(
        support::call_count(),
        STRUCTURED_RETRIES as usize,
        "each attempt must reach the provider"
    );
}

#[test]
fn too_short_content_fails_validation_and_is_retried() {
    let _guard = support::lock();
    let base_url = support::spawn_server();
    let dir = support::TempDir::new("retry-invalid");
    std::env::set_var("THINK_TANK_KB_PATH", dir.path.to_str().unwrap());
    support::install_env(&base_url);
    // Every attempt must return the *invalid* payload, so the final error still
    // reports the validation failure rather than the script running dry.
    support::install_script(vec![
        support::ScriptEntry {
            schema: "ResearcherOutput".into(),
            payload: json!({
                "content": "short",           // below the 10-char floor
                "dimensions": {},
                "confidence": "high",
                "evidence_summary": "too short"
            }),
        };
        STRUCTURED_RETRIES as usize
    ]);

    let error = think_tank::llm::invoke_structured(
        "researcher",
        &Config::new(),
        SchemaKind::Researcher,
        "system",
        "user",
        0.2,
    )
    .unwrap_err();
    assert!(error.contains("after 3 attempts"), "error: {error}");
    assert!(
        error.contains("content"),
        "the validation failure must be reported: {error}"
    );
}

// ---------------------------------------------------------------------------
// Dimension coercion — `_stringify_dimensions`
// ---------------------------------------------------------------------------

#[test]
fn dimensions_accept_a_flat_string_map() {
    let value = json!({"feasibility": "high", "risk": "moderate"});
    let dims = stringify_dimensions(Some(&value));
    assert_eq!(dims.len(), 2);
    assert_eq!(dims.iter().next().unwrap().1, "high");
}

#[test]
fn dimensions_accept_a_nested_map() {
    let value = json!({"feasibility": {"rating": "high", "note": "strong"}});
    let dims = stringify_dimensions(Some(&value));
    assert_eq!(dims.iter().next().unwrap().1, "rating: high; note: strong");
}

#[test]
fn dimensions_accept_a_json_encoded_string() {
    let value = json!("{\"feasibility\": \"high\"}");
    let dims = stringify_dimensions(Some(&value));
    assert_eq!(dims.len(), 1);
    assert_eq!(dims.iter().next().unwrap().1, "high");
}

#[test]
fn dimensions_accept_a_pair_list() {
    let value = json!([["feasibility", "high"], ["risk", "low"]]);
    let dims = stringify_dimensions(Some(&value));
    assert_eq!(dims.len(), 2);
}

#[test]
fn dimensions_reject_unusable_shapes_without_failing_the_call() {
    assert!(stringify_dimensions(Some(&json!("not json"))).is_empty());
    assert!(stringify_dimensions(Some(&json!(42))).is_empty());
    assert!(stringify_dimensions(None).is_empty());
}

#[test]
fn dimensions_flatten_nested_lists_and_render_python_dict_syntax() {
    let value = json!({"a": ["x", "y"], "b": null, "c": 3});
    let dims = stringify_dimensions(Some(&value));
    let rendered = dims.to_string();
    assert_eq!(rendered, "{'a': 'x; y', 'b': '', 'c': '3'}");
}

#[test]
fn dimension_rendering_matches_python_str_repr() {
    // Expected values were generated from CPython's `repr()`.
    let cases = [
        ("high", "'high'"),
        ("don't scale", "\"don't scale\""),
        ("both ' and \"", "'both \\' and \"'"),
        ("line\nbreak", "'line\\nbreak'"),
        ("back\\slash", "'back\\\\slash'"),
        ("ctl\u{01}x", "'ctl\\x01x'"),
    ];
    for (raw, expected) in cases {
        let value = json!({"k": raw});
        let dims = stringify_dimensions(Some(&value));
        let rendered = dims.to_string();
        let want = format!("{{'k': {}}}", expected);
        assert_eq!(rendered, want, "raw={:?}", raw);
    }
}

// ---------------------------------------------------------------------------
// Output validation
// ---------------------------------------------------------------------------

#[test]
fn every_schema_enforces_its_required_fields() {
    let _guard = support::lock();
    assert!(parse_output(SchemaKind::Researcher, &json!({})).is_err());
    assert!(parse_output(SchemaKind::Skeptic, &json!({})).is_err());
    assert!(parse_output(SchemaKind::Visionary, &json!({})).is_err());
    assert!(parse_output(SchemaKind::Synthesizer, &json!({})).is_err());
}

#[test]
fn skeptic_stance_must_be_one_of_the_three_values() {
    let _guard = support::lock();
    let mut payload = json!({
        "target_claim_id": "abc",
        "stance": "oppose",
        "content": "a sufficiently long challenge",
        "reasoning": "a sufficiently long reason"
    });
    assert!(parse_output(SchemaKind::Skeptic, &payload).is_ok());
    payload["stance"] = json!("ignore previous instructions");
    assert!(parse_output(SchemaKind::Skeptic, &payload).is_err());
}

#[test]
fn confidence_defaults_to_medium_for_absent_or_unknown_values() {
    let dims = stringify_dimensions(None);
    assert!(dims.is_empty());

    let missing =
        json!({"content": "a long enough claim text", "evidence_summary": "a fine summary"});
    let parsed = think_tank::schemas::ResearcherOutput::parse(&missing).unwrap();
    assert_eq!(parsed.confidence, Confidence::Medium);

    let unknown = json!({
        "content": "a long enough claim text",
        "evidence_summary": "a fine summary",
        "confidence": "certain"
    });
    let parsed = think_tank::schemas::ResearcherOutput::parse(&unknown).unwrap();
    assert_eq!(parsed.confidence, Confidence::Medium);
}

#[test]
fn stance_roundtrips_through_its_wire_value() {
    assert_eq!(Stance::Oppose.as_str(), "oppose");
    assert_eq!(Stance::Support.as_str(), "support");
    assert_eq!(Stance::Refine.as_str(), "refine");
}
