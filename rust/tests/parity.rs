//! Gate 2 — golden fixture parity with the Python reference.
//!
//! Each scenario replays the scripted LLM payloads the Python recorder captured
//! and asserts the Rust trace matches the Python trace field for field.

mod support;

use serde_json::{json, Value};
use think_tank::graph::{run, NoObserver, RunServices};
use think_tank::llm::{embedding_collection_name, resolve_embedding_provider};
use think_tank::runner::{initial_state, prepare_run, Config};
use think_tank::state::ThinkTankState;

use support::{fixture_scenarios, install_env, install_script, normalise, script_for, TempDir};

fn run_scenario(scenario: &Value) -> (ThinkTankState, Value) {
    let base_url = support::spawn_server();
    let dir = TempDir::new("golden");
    std::env::set_var("THINK_TANK_KB_PATH", dir.path.to_str().unwrap());
    install_env(&base_url);
    install_script(script_for(scenario));

    let prepared = prepare_run().expect("prepare run against stub");
    let config_json = scenario.get("config").cloned().unwrap_or(json!({}));
    let mut config = Config::new();
    let mut overrides = std::collections::BTreeMap::new();
    for (key, value) in config_json.as_object().into_iter().flatten() {
        overrides.insert(key.clone(), value.to_string().trim_matches('"').to_string());
    }
    config = config.with_overrides(&overrides);

    let topic = scenario.get("topic").and_then(|t| t.as_str()).unwrap();
    let state = initial_state(topic, Some(config));
    let services = RunServices {
        vector_store: prepared.vector_store,
    };
    let final_state = run(state, &services, &mut NoObserver).expect("deliberation run");

    let trace = json!({
        "claims": final_state.claims,
        "challenges": final_state.challenges,
        "expansions": final_state.expansions,
        "syntheses": final_state.syntheses,
        "expansion": final_state.expansion,
        "synthesis": final_state.synthesis,
        "current_round": final_state.current_round,
        "alignment_score": final_state.alignment_score,
    });
    (final_state, trace)
}

#[test]
fn rust_trace_matches_python_golden() {
    let _guard = support::lock();
    let scenarios = fixture_scenarios();
    assert!(!scenarios.is_empty(), "no fixture scenarios recorded");

    for scenario in &scenarios {
        let name = scenario.get("name").and_then(|n| n.as_str()).unwrap();
        let (final_state, trace) = run_scenario(scenario);

        let tokens = support::id_tokens(
            &trace["claims"].as_array().unwrap().clone(),
            &trace["challenges"].as_array().unwrap().clone(),
            &trace["expansions"].as_array().unwrap().clone(),
            &trace["syntheses"].as_array().unwrap().clone(),
            trace["expansion"].as_object().map(|_| &trace["expansion"]),
            trace["synthesis"].as_object().map(|_| &trace["synthesis"]),
        );
        let actual = normalise(&trace, &tokens);
        let expected = &scenario["expected"];

        for field in ["claims", "challenges", "expansions", "syntheses"] {
            assert_eq!(
                actual[field], expected[field],
                "[{}] {} mismatch\n rust: {}\n python: {}",
                name, field, actual[field], expected[field]
            );
        }
        assert_eq!(
            actual["alignment_score"], expected["alignment_score"],
            "[{}] alignment_score",
            name
        );
        assert_eq!(
            actual["current_round"], expected["current_round"],
            "[{}] current_round",
            name
        );
        for field in ["expansion", "synthesis"] {
            let expected_field = if expected[field].is_null() {
                Value::Null
            } else {
                normalise(&expected[field], &tokens)
            };
            assert_eq!(
                actual[field], expected_field,
                "[{}] {} mismatch\n rust: {}\n python: {}",
                name, field, actual[field], expected_field
            );
        }

        // The whole scripted call sequence must be consumed in the same order.
        // The recorder stores the pydantic class stem ("Researcher"); the stub
        // server reports the advertised function name ("ResearcherOutput").
        let expected_order: Vec<String> = scenario["script"]
            .as_array()
            .unwrap()
            .iter()
            .map(|e| {
                let stem = e["schema"].as_str().unwrap();
                if stem.ends_with("Output") {
                    stem.to_string()
                } else {
                    format!("{}Output", stem)
                }
            })
            .collect();
        assert_eq!(
            support::call_order(),
            expected_order,
            "[{}] structured-call order",
            name
        );
        assert_eq!(
            final_state.synthesis.is_some(),
            !expected["synthesis"].is_null(),
            "[{}] synthesis presence",
            name
        );
    }
}

#[test]
fn rendered_rounds_match_python_cli() {
    let _guard = support::lock();
    for scenario in fixture_scenarios() {
        let name = scenario["name"].as_str().unwrap().to_string();
        let expected_rounds: Vec<String> = scenario["rendered_rounds"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r.as_str().unwrap().to_string())
            .collect();

        let base_url = support::spawn_server();
        let dir = TempDir::new("render");
        std::env::set_var("THINK_TANK_KB_PATH", dir.path.to_str().unwrap());
        install_env(&base_url);
        install_script(script_for(&scenario));

        let prepared = prepare_run().expect("prepare run");
        let topic = scenario["topic"].as_str().unwrap();
        let config_json = scenario["config"].clone();
        let mut overrides = std::collections::BTreeMap::new();
        for (key, value) in config_json.as_object().into_iter().flatten() {
            overrides.insert(key.clone(), value.to_string().trim_matches('"').to_string());
        }
        let config = Config::new().with_overrides(&overrides);
        let state = initial_state(topic, Some(config));
        let services = RunServices {
            vector_store: prepared.vector_store,
        };

        struct Collect(Vec<String>);
        impl think_tank::graph::Observer for Collect {
            fn on_round(&mut self, state: &ThinkTankState) {
                self.0.push(think_tank::print::render_state(state));
            }
        }
        let mut observer = Collect(Vec::new());
        let final_state = run(state, &services, &mut observer).expect("run");

        let trace = json!({
            "claims": final_state.claims,
            "challenges": final_state.challenges,
            "expansions": final_state.expansions,
            "syntheses": final_state.syntheses,
            "expansion": final_state.expansion,
            "synthesis": final_state.synthesis,
        });
        let tokens = support::id_tokens(
            trace["claims"].as_array().unwrap(),
            trace["challenges"].as_array().unwrap(),
            trace["expansions"].as_array().unwrap(),
            trace["syntheses"].as_array().unwrap(),
            trace["expansion"].as_object().map(|_| &trace["expansion"]),
            trace["synthesis"].as_object().map(|_| &trace["synthesis"]),
        );

        assert_eq!(
            observer.0.len(),
            expected_rounds.len(),
            "[{}] round count",
            name
        );
        for (index, (actual, expected)) in observer.0.iter().zip(expected_rounds.iter()).enumerate()
        {
            let actual_norm = normalise(&Value::String(actual.clone()), &tokens);
            let expected_norm = normalise(&Value::String(expected.clone()), &tokens);
            assert_eq!(
                actual_norm, expected_norm,
                "[{}] rendered round {} differs\n--- rust ---\n{}\n--- python ---\n{}",
                name, index, actual, expected
            );
        }
    }
}

#[test]
fn embedding_collection_name_is_namespaced_per_embedding_space() {
    let _guard = support::lock();
    std::env::set_var("THINK_TANK_EMBEDDING_PROVIDER", "openrouter");
    std::env::remove_var("THINK_TANK_EMBEDDING_MODEL");
    let name = embedding_collection_name(None, None).unwrap();
    assert_eq!(
        name,
        "think_tank_kb__openrouter-openai-text-embedding-3-small"
    );

    let provider = resolve_embedding_provider(None).unwrap();
    assert_eq!(provider.name, "openrouter");
    assert!(provider.supports_embeddings());
}
