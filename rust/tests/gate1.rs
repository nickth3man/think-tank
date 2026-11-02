//! Gate 1 — stub-server integration of the real loop.
//!
//! Drives the actual node bodies, arbiter, and router against a local
//! OpenAI-protocol stub server: no network, no credentials, deterministic.

mod support;

use serde_json::json;
use think_tank::agents::{arbiter_node, route_after_arbiter, Route};
use think_tank::graph::{run, NoObserver, RunServices};
use think_tank::runner::{initial_state, prepare_run, Config};
use think_tank::schemas::{now, Challenge, Claim, Confidence, Stance};
use think_tank::state::ThinkTankState;

use support::{hash_embed, install_env, install_script, ScriptEntry, TempDir};

fn claim(round: u32, content: &str, embedding: Vec<f64>) -> Claim {
    Claim {
        id: format!("claim-{}", round),
        agent_id: "researcher".to_string(),
        round,
        content: content.to_string(),
        dimensions: Default::default(),
        confidence: Confidence::High,
        evidence_summary: "evidence".to_string(),
        embedding,
        created_at: now(),
    }
}

fn challenge(round: u32, stance: Stance) -> Challenge {
    Challenge {
        id: format!("challenge-{}", round),
        agent_id: "skeptic".to_string(),
        target_claim_id: format!("claim-{}", round),
        round,
        stance,
        content: "a substantive challenge".to_string(),
        reasoning: "because".to_string(),
        resolved: false,
        created_at: now(),
    }
}

// ---------------------------------------------------------------------------
// Arbiter math — the formula the rewrite must reproduce
// ---------------------------------------------------------------------------

#[test]
fn arbiter_score_is_eighty_twenty_without_resolution_term() {
    let mut state = initial_state("topic", None);
    // Round 0: one claim, no prior -> semantic 0.0; one OPPOSE challenge.
    state
        .claims
        .push(claim(0, "first position text", vec![1.0, 0.0]));
    state.challenges.push(challenge(0, Stance::Oppose));

    let after = arbiter_node(&state).expect("arbiter");
    // 0.80 * 0.0 + 0.20 * (1 - 1.0) = 0.0
    assert_eq!(after.alignment_score, 0.0);
    assert!(after.expansion.is_some(), "should loop back");
    assert!(after.synthesis.is_none());
}

#[test]
fn alignment_uses_prior_round_embeddings_and_opposition_only() {
    let mut state = initial_state("topic", None);
    state.current_round = 1;
    state
        .claims
        .push(claim(0, "prior position text", vec![1.0, 0.0]));
    state
        .claims
        .push(claim(1, "current position text", vec![1.0, 0.0]));
    // SUPPORT stance is not opposition, so opposition ratio is 0.
    state.challenges.push(challenge(1, Stance::Support));

    let after = arbiter_node(&state).expect("arbiter");
    // semantic = 1.0 (identical embeddings), opposition = 0.0
    // 0.80 * 1.0 + 0.20 * 1.0 = 1.0
    assert_eq!(after.alignment_score, 1.0);
    assert!(after.synthesis.is_some(), "should converge");
    assert_eq!(after.current_round, 2);
}

#[test]
fn min_rounds_forces_another_round_even_at_full_alignment() {
    let mut state = initial_state("topic", None);
    state
        .claims
        .push(claim(0, "only position text", vec![1.0, 0.0]));
    let after = arbiter_node(&state).expect("arbiter");
    // round 0 -> rounds_completed = 1 < min_rounds 2, so loop despite alignment.
    assert!(after.expansion.is_some());
}

#[test]
fn max_rounds_forces_best_effort_synthesis() {
    let config = Config::new().with_overrides(&std::collections::BTreeMap::from([(
        "max_rounds".to_string(),
        "2".to_string(),
    )]));
    let mut state = initial_state("topic", Some(config));
    state.current_round = 1;
    state
        .claims
        .push(claim(1, "current position text", vec![0.0, 1.0]));
    state.challenges.push(challenge(1, Stance::Oppose));

    let after = arbiter_node(&state).expect("arbiter");
    assert!(after.synthesis.is_some(), "max_rounds must terminate");
    let synthesis = after.synthesis.unwrap();
    assert_eq!(synthesis.rounds_taken, 2);
    // No synthesizer attempt existed, so the deterministic fallback ran.
    assert!(synthesis.content.starts_with("Max rounds reached"));
}

#[test]
fn expansion_directive_targets_next_round_and_weak_dimensions() {
    let mut state = initial_state("topic", None);
    let mut first = claim(0, "first position text", vec![1.0, 0.0]);
    first.dimensions.insert("feasibility".into(), "high".into());
    first.dimensions.insert("risk".into(), "low".into());
    let mut second = claim(0, "second position text", vec![-1.0, 0.0]);
    second.dimensions.insert("feasibility".into(), "low".into());
    second.dimensions.insert("risk".into(), "low".into());
    state.claims.push(first);
    state.claims.push(second);

    let after = arbiter_node(&state).expect("arbiter");
    let expansion = after.expansion.expect("expansion");
    assert_eq!(expansion.round, 1);
    // Only `feasibility` has more than one distinct value.
    assert_eq!(expansion.focus_dimensions, vec!["feasibility".to_string()]);
    assert!(expansion.prompt.contains("feasibility"));
}

#[test]
fn router_ends_only_when_a_synthesis_exists() {
    let mut state = initial_state("topic", None);
    assert_eq!(route_after_arbiter(&state), Route::Researcher);
    let after = arbiter_node(&{
        let mut s = state.clone();
        s.current_round = 1;
        s.claims
            .push(claim(0, "prior position text", vec![1.0, 0.0]));
        s.claims
            .push(claim(1, "current position text", vec![1.0, 0.0]));
        s
    })
    .expect("arbiter");
    state = after;
    assert!(state.synthesis.is_some());
    assert_eq!(route_after_arbiter(&state), Route::End);
}

// ---------------------------------------------------------------------------
// Full loop against the stub server
// ---------------------------------------------------------------------------

fn script() -> Vec<ScriptEntry> {
    vec![
        ScriptEntry {
            schema: "ResearcherOutput".into(),
            payload: json!({
                "content": "Evidence indicates remote work reliably raises productivity.",
                "dimensions": {"feasibility": "high", "risk": "moderate"},
                "confidence": "high",
                "evidence_summary": "Two large-sample studies agree."
            }),
        },
        ScriptEntry {
            schema: "SkepticOutput".into(),
            payload: json!({
                "target_claim_id": "__FIRST_CLAIM_ID__",
                "stance": "oppose",
                "content": "The sample covers knowledge workers only, limiting generality.",
                "reasoning": "Scope of cited samples is narrower than the claim."
            }),
        },
        ScriptEntry {
            schema: "VisionaryOutput".into(),
            payload: json!({
                "content": "Treat the office as a scheduled collaboration venue, not a default.",
                "related_claim_ids": ["__FIRST_CLAIM_ID__"],
                "novelty_rationale": "Reframes the office as a scheduling primitive."
            }),
        },
        ScriptEntry {
            schema: "SynthesizerOutput".into(),
            payload: json!({
                "content": "Individual throughput rises while coordination cost rises too.",
                "incorporated_claim_ids": ["__FIRST_CLAIM_ID__"],
                "resolved_tensions": ["Scoped the productivity claim."],
                "remaining_tensions": ["Coordination cost is unquantified."],
                "confidence": "medium"
            }),
        },
        ScriptEntry {
            schema: "ResearcherOutput".into(),
            payload: json!({
                "content": "Evidence indicates remote work reliably raises productivity.",
                "dimensions": {"feasibility": "high", "risk": "moderate"},
                "confidence": "high",
                "evidence_summary": "Two large-sample studies agree."
            }),
        },
        ScriptEntry {
            schema: "SkepticOutput".into(),
            payload: json!({
                "target_claim_id": "__FIRST_CLAIM_ID__",
                "stance": "refine",
                "content": "The sample covers knowledge workers only, limiting generality.",
                "reasoning": "Scope of cited samples is narrower than the claim."
            }),
        },
        ScriptEntry {
            schema: "VisionaryOutput".into(),
            payload: json!({
                "content": "Treat the office as a scheduled collaboration venue, not a default.",
                "related_claim_ids": ["__FIRST_CLAIM_ID__"],
                "novelty_rationale": "Reframes the office as a scheduling primitive."
            }),
        },
        ScriptEntry {
            schema: "SynthesizerOutput".into(),
            payload: json!({
                "content": "Individual throughput rises while coordination cost rises too.",
                "incorporated_claim_ids": ["__FIRST_CLAIM_ID__"],
                "resolved_tensions": [],
                "remaining_tensions": [],
                "confidence": "medium"
            }),
        },
    ]
}

#[test]
fn stub_server_drives_the_full_loop_with_correct_ordering() {
    let _guard = support::lock();
    let base_url = support::spawn_server();
    let dir = TempDir::new("gate1");
    std::env::set_var("THINK_TANK_KB_PATH", dir.path.to_str().unwrap());
    install_env(&base_url);
    install_script(script());

    let prepared = prepare_run().expect("prepare run");
    assert!(prepared.seeded, "empty store must be seeded");
    let state = initial_state("Should companies adopt fully remote work?", None);
    let services = RunServices {
        vector_store: prepared.vector_store,
    };
    let final_state = run(state, &services, &mut NoObserver).expect("deliberation");

    assert_eq!(
        support::call_order(),
        vec![
            "ResearcherOutput",
            "SkepticOutput",
            "VisionaryOutput",
            "SynthesizerOutput",
            "ResearcherOutput",
            "SkepticOutput",
            "VisionaryOutput",
            "SynthesizerOutput",
        ],
        "node ordering within each round"
    );

    // Whole-list extension: no reducer drops history.
    assert_eq!(final_state.claims.len(), 2);
    assert_eq!(final_state.challenges.len(), 2);
    assert_eq!(final_state.expansions.len(), 2);
    assert_eq!(final_state.syntheses.len(), 2);
    assert_eq!(final_state.claims[0].round, 0);
    assert_eq!(final_state.claims[1].round, 1);

    // Convergence: identical claim text across rounds -> alignment 1.0.
    assert_eq!(final_state.alignment_score, 1.0);
    assert_eq!(final_state.current_round, 2);
    let synthesis = final_state.synthesis.expect("final synthesis");
    assert_eq!(synthesis.rounds_taken, 2);
    assert_eq!(synthesis.alignment_score, 1.0);
    assert_eq!(synthesis.contributing_claim_ids.len(), 1);
    assert!(final_state.expansion.is_none());

    // Evidence is retrieved once and cached in state for later rounds.
    assert!(!final_state.evidence.is_empty());
    assert!(support::call_count() == 8, "all scripted calls consumed");
}

#[test]
fn researcher_embeds_with_the_configured_embedding_provider() {
    let _guard = support::lock();
    let base_url = support::spawn_server();
    let dir = TempDir::new("gate1-embed");
    std::env::set_var("THINK_TANK_KB_PATH", dir.path.to_str().unwrap());
    install_env(&base_url);
    install_script(script());

    let prepared = prepare_run().expect("prepare");
    let state = initial_state("Should companies adopt fully remote work?", None);
    let services = RunServices {
        vector_store: prepared.vector_store,
    };
    let final_state = run(state, &services, &mut NoObserver).expect("run");

    let expected = hash_embed(&final_state.claims[0].content);
    assert_eq!(final_state.claims[0].embedding.len(), expected.len());
    for (actual, want) in final_state.claims[0].embedding.iter().zip(expected.iter()) {
        assert!(
            (actual - want).abs() < 1e-12,
            "embedding must match the stub"
        );
    }
}

// ---------------------------------------------------------------------------
// CLI — the binary must exit 0 on a deterministic stub run
// ---------------------------------------------------------------------------

#[test]
fn cli_exits_zero_on_a_stub_run() {
    use std::process::Command;

    let _guard = support::lock();
    let base_url = support::spawn_server();
    let dir = TempDir::new("cli");
    install_env(&base_url);
    install_script(script());

    let output = Command::new(env!("CARGO_BIN_EXE_think-tank"))
        .arg("Should companies adopt fully remote work?")
        .env("THINK_TANK_KB_PATH", dir.path.to_str().unwrap())
        .env("THINK_TANK_PROVIDER", "ollama_cloud")
        .env("THINK_TANK_EMBEDDING_PROVIDER", "openrouter")
        .env(
            "THINK_TANK_BASE_URL_OLLAMA_CLOUD",
            format!("{}/v1", base_url),
        )
        .env("THINK_TANK_BASE_URL_OPENROUTER", format!("{}/v1", base_url))
        .env("OLLAMA_CLOUD_API_KEY", "stub-chat-key")
        .env("OPENROUTER_API_KEY", "stub-embed-key")
        .output()
        .expect("run the CLI binary");

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "CLI exited {:?}\n--- stdout ---\n{}\n--- stderr ---\n{}",
        output.status.code(),
        stdout,
        stderr
    );
    assert!(stdout.contains("THINK TANK — Topic:"), "topic header");
    assert!(
        stdout.contains("FINAL SYNTHESIS"),
        "final synthesis section"
    );
    assert!(
        stdout.contains("DELIBERATION COMPLETE"),
        "completion footer"
    );
    assert!(stdout.contains("Round ............. 0"), "round 0 printed");
    assert!(stdout.contains("Round ............. 1"), "round 1 printed");
}

#[test]
fn cli_without_credentials_exits_nonzero_and_says_what_is_missing() {
    use std::process::Command;

    let _guard = support::lock();
    let dir = TempDir::new("cli-nocreds");
    let output = Command::new(env!("CARGO_BIN_EXE_think-tank"))
        .arg("topic")
        .env("THINK_TANK_KB_PATH", dir.path.to_str().unwrap())
        .env("THINK_TANK_PROVIDER", "ollama_cloud")
        .env("THINK_TANK_EMBEDDING_PROVIDER", "openrouter")
        .env_remove("OLLAMA_CLOUD_API_KEY")
        .env_remove("OPENROUTER_API_KEY")
        .output()
        .expect("run the CLI binary");

    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("Missing credentials"), "stderr: {}", stderr);
    assert!(stderr.contains("OLLAMA_CLOUD_API_KEY"));
    assert!(stderr.contains("OPENROUTER_API_KEY"));
}

#[test]
fn state_round_filters_are_consistent_with_the_arbiter() {
    let mut state = initial_state("topic", None);
    state.claims.push(claim(0, "round zero text", vec![1.0]));
    state.claims.push(claim(1, "round one text", vec![1.0]));
    state.challenges.push(challenge(1, Stance::Support));
    assert_eq!(state.claims_for_round(0).len(), 1);
    assert_eq!(state.claims_for_round(1).len(), 1);
    assert_eq!(state.challenges_for_round(0).len(), 0);
    assert_eq!(state.challenges_for_round(1).len(), 1);
}

#[allow(dead_code)]
fn unused_state_helper_guard(_s: ThinkTankState) {}
