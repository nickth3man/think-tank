//! The deliberation report the UI renders.
//!
//! One JSON document per run: every field of [`ThinkTankState`], the arbiter's
//! scoring broken into the terms it actually uses, the retrieved evidence with
//! its similarity scores, and the telemetry spans. Nothing here is invented for
//! display — each value either comes from the state the loop produced, is
//! recomputed with the same functions the arbiter uses, or is measured by the
//! span recorder.
//!
//! The UI promises to show every field a run produces, so this module also
//! emits the field inventory (`state_fields`) the UI checks itself against.

use serde_json::{json, Value};

use crate::agents::arbiter::{
    self, challenge_resolution_rate, opposition_ratio, pairwise_alignment,
};
use crate::graph::{run, Observer, RunServices};
use crate::runner::{initial_state, Config};
use crate::state::ThinkTankState;
use crate::telemetry::recorder;

/// Collects the state once per distinct round, like `stream_mode="values"`.
struct SnapshotObserver {
    snapshots: Vec<ThinkTankState>,
}

impl Observer for SnapshotObserver {
    fn on_round(&mut self, state: &ThinkTankState) {
        self.snapshots.push(state.clone());
    }
}

fn round4(value: f64) -> f64 {
    format!("{:.4}", value).parse().unwrap_or(value)
}

fn config_from(scenario: &Value) -> Config {
    let mut overrides = std::collections::BTreeMap::new();
    if let Some(map) = scenario.get("config").and_then(|c| c.as_object()) {
        for (key, value) in map {
            let text = match value {
                Value::String(s) => s.clone(),
                other => other.to_string(),
            };
            overrides.insert(key.clone(), text);
        }
    }
    Config::new().with_overrides(&overrides)
}

/// A run's score decomposed into the terms the arbiter actually sums.
fn score_parts(state: &ThinkTankState, round: u32) -> Value {
    let latest: Vec<&crate::schemas::Claim> =
        state.claims.iter().filter(|c| c.round == round).collect();
    let prior: Vec<&crate::schemas::Claim> =
        state.claims.iter().filter(|c| c.round < round).collect();
    let latest_challenges: Vec<&crate::schemas::Challenge> = state
        .challenges
        .iter()
        .filter(|c| c.round == round)
        .collect();

    let semantic = round4(pairwise_alignment(&latest, &prior));
    let opposition = round4(opposition_ratio(&latest_challenges));
    let resolution = round4(challenge_resolution_rate(&latest_challenges));
    let semantic_term = round4(0.80 * semantic);
    let opposition_term = round4(0.20 * (1.0 - opposition));

    // The exact comparisons the arbiter averages: pairs within this round, then
    // each of this round's claims against every earlier claim.
    let mut pairs: Vec<Value> = Vec::new();
    for (i, a) in latest.iter().enumerate() {
        for b in latest.iter().skip(i + 1) {
            pairs.push(json!({
                "a": a.id, "b": b.id, "scope": "same_round",
                "cosine": round4(arbiter::cosine_similarity(&a.embedding, &b.embedding)),
            }));
        }
    }
    if !latest.is_empty() && !prior.is_empty() {
        for a in &latest {
            for b in &prior {
                pairs.push(json!({
                    "a": a.id, "b": b.id, "scope": "earlier_round",
                    "cosine": round4(arbiter::cosine_similarity(&a.embedding, &b.embedding)),
                }));
            }
        }
    }

    json!({
        "comparisons": pairs,
        "semantic_alignment": semantic,
        "opposition_ratio": opposition,
        "challenge_resolution_rate": resolution,
        "weights": {"semantic": 0.80, "opposition": 0.20},
        "semantic_term": semantic_term,
        "opposition_term": opposition_term,
        "sum_before_clamp": round4(semantic_term + opposition_term),
        "claim_count": latest.len(),
        "prior_claim_count": prior.len(),
        "challenge_count": latest_challenges.len(),
    })
}

fn round_verdict(
    state: &ThinkTankState,
    threshold: f64,
    min_rounds: u32,
    max_rounds: u32,
) -> Value {
    match (&state.synthesis, &state.expansion) {
        (Some(synthesis), _) => {
            let converged =
                synthesis.alignment_score >= threshold && synthesis.rounds_taken >= min_rounds;
            json!({
                "kind": if converged { "converged" } else { "forced" },
                "rounds_taken": synthesis.rounds_taken,
                "reason": if converged {
                    format!(
                        "The score {:.4} reached the target of {:.2}, and at least {} round(s) had run.",
                        synthesis.alignment_score, threshold, min_rounds
                    )
                } else {
                    format!(
                        "The maximum of {} round(s) was reached before the score {:.4} could reach the target of {:.2}.",
                        max_rounds, synthesis.alignment_score, threshold
                    )
                },
            })
        }
        (None, Some(expansion)) => json!({
            "kind": "continue",
            "next_round": expansion.round,
            "reason": format!(
                "The score {:.4} was below the target of {:.2}, so the agents go round again.",
                state.alignment_score, threshold
            ),
        }),
        (None, None) => json!({
            "kind": "unknown",
            "reason": "No verdict was recorded for this round.",
        }),
    }
}

fn artifacts_for_round(state: &ThinkTankState, round: u32) -> Value {
    json!({
        "claims": state.claims.iter().filter(|c| c.round == round).collect::<Vec<_>>(),
        "challenges": state.challenges.iter().filter(|c| c.round == round).collect::<Vec<_>>(),
        "lateral_ideas": state.expansions.iter().filter(|e| e.round == round).collect::<Vec<_>>(),
        "synthesis_attempts": state.syntheses.iter().filter(|s| s.round == round).collect::<Vec<_>>(),
    })
}

/// Every field the UI is expected to render, and where it lives.
///
/// The UI grades itself against this list: a field that is neither shown nor
/// listed as deliberately hidden is a defect, not a design choice.
const STATE_FIELDS: &[(&str, &str, &str)] = &[
    ("topic", "run", "header"),
    ("config", "run", "run settings panel"),
    ("current_round", "run", "round strip and header"),
    ("alignment_score", "run", "score panel"),
    ("evidence", "run", "evidence panel"),
    ("claims", "artifacts", "claims list per round"),
    ("challenges", "artifacts", "challenges list per round"),
    ("expansions", "artifacts", "lateral ideas per round"),
    ("syntheses", "artifacts", "synthesis attempts per round"),
    ("expansion", "artifacts", "arbiter directive panel"),
    ("synthesis", "artifacts", "final answer panel"),
    ("claim.id", "claim", "short id chip, full id on expand"),
    ("claim.agent_id", "claim", "agent badge"),
    ("claim.round", "claim", "round heading"),
    ("claim.content", "claim", "claim body"),
    ("claim.dimensions", "claim", "dimension bars"),
    ("claim.confidence", "claim", "confidence chip"),
    ("claim.evidence_summary", "claim", "claim evidence line"),
    ("claim.embedding", "claim", "meaning fingerprint sparkline"),
    ("claim.created_at", "claim", "timestamp on expand"),
    ("challenge.id", "challenge", "short id chip"),
    ("challenge.agent_id", "challenge", "agent badge"),
    ("challenge.target_claim_id", "challenge", "target link"),
    ("challenge.round", "challenge", "round heading"),
    ("challenge.stance", "challenge", "stance chip"),
    ("challenge.content", "challenge", "challenge body"),
    ("challenge.reasoning", "challenge", "reasoning line"),
    ("challenge.resolved", "challenge", "open/resolved chip"),
    ("challenge.created_at", "challenge", "timestamp on expand"),
    ("expansion.id", "directive", "directive panel"),
    ("expansion.round", "directive", "directive panel"),
    ("expansion.focus_dimensions", "directive", "directive panel"),
    ("expansion.prompt", "directive", "directive panel"),
    (
        "expansion.disagreement_summary",
        "directive",
        "directive panel",
    ),
    ("expansion.created_at", "directive", "timestamp on expand"),
    ("synthesis.id", "final", "final answer panel"),
    ("synthesis.content", "final", "final answer panel"),
    (
        "synthesis.contributing_claim_ids",
        "final",
        "final answer panel",
    ),
    ("synthesis.alignment_score", "final", "final answer panel"),
    ("synthesis.rounds_taken", "final", "final answer panel"),
    (
        "synthesis.unresolved_challenges",
        "final",
        "final answer panel",
    ),
    ("synthesis.created_at", "final", "timestamp on expand"),
    ("lateral_idea.id", "lateral", "lateral idea card"),
    ("lateral_idea.agent_id", "lateral", "agent badge"),
    ("lateral_idea.round", "lateral", "round heading"),
    ("lateral_idea.content", "lateral", "lateral idea card"),
    (
        "lateral_idea.related_claim_ids",
        "lateral",
        "lateral idea card",
    ),
    (
        "lateral_idea.novelty_rationale",
        "lateral",
        "lateral idea card",
    ),
    ("lateral_idea.created_at", "lateral", "timestamp on expand"),
    ("attempt.id", "attempt", "synthesis attempt card"),
    ("attempt.agent_id", "attempt", "agent badge"),
    ("attempt.round", "attempt", "round heading"),
    ("attempt.content", "attempt", "synthesis attempt card"),
    (
        "attempt.incorporated_claim_ids",
        "attempt",
        "synthesis attempt card",
    ),
    (
        "attempt.resolved_tensions",
        "attempt",
        "synthesis attempt card",
    ),
    (
        "attempt.remaining_tensions",
        "attempt",
        "synthesis attempt card",
    ),
    ("attempt.confidence", "attempt", "confidence chip"),
    ("attempt.created_at", "attempt", "timestamp on expand"),
];

fn state_field_inventory() -> Value {
    Value::Array(
        STATE_FIELDS
            .iter()
            .map(|(field, group, place)| json!({"field": field, "group": group, "where": place}))
            .collect(),
    )
}

/// Build the full report for one recorded scenario.
///
/// The real loop runs against the replay stub, so every artefact is produced by
/// the same node bodies a live run uses.
pub fn replay_report(scenario: &Value) -> Result<Value, String> {
    use crate::devstub;

    let base_url = devstub::spawn_server();
    let dir = devstub::TempDir::new("ui");
    std::env::set_var("THINK_TANK_KB_PATH", dir.path.to_str().unwrap_or_default());
    devstub::install_env(&base_url);
    devstub::install_script(devstub::script_for(scenario));

    let prepared = crate::runner::prepare_run().map_err(|e| e.to_string())?;
    let config = config_from(scenario);
    let topic = scenario
        .get("topic")
        .and_then(|t| t.as_str())
        .unwrap_or_default()
        .to_string();
    let start = initial_state(&topic, Some(config.clone()));

    let run_id = format!("ui-{}", crate::schemas::now().timestamp_millis());
    recorder().enable(true);
    recorder().reset(Some(&run_id));

    let mut observer = SnapshotObserver {
        snapshots: Vec::new(),
    };
    let services = RunServices {
        vector_store: prepared.vector_store.clone(),
    };
    let final_state =
        crate::telemetry::run_scope(&run_id, || run(start.clone(), &services, &mut observer))?;

    // The arbiter reads these keys itself and falls back to its own constants,
    // so the effective values are resolved the same way, not via `runner`.
    let effective = &start.config;
    let threshold = effective
        .get("alignment_threshold")
        .and_then(|v| v.parse().ok())
        .unwrap_or(arbiter::ALIGNMENT_THRESHOLD);
    let min_rounds = effective.min_rounds_or(arbiter::MIN_ROUNDS);
    let max_rounds = effective.max_rounds_or(arbiter::MAX_ROUNDS);

    // Snapshots: the state before any node ran, then the state after each round.
    let mut rounds: Vec<Value> = Vec::new();
    for (index, snapshot) in observer.snapshots.iter().enumerate() {
        if index == 0 {
            continue;
        }
        let round = snapshot.current_round.saturating_sub(1);
        rounds.push(json!({
            "round": round,
            "number": round + 1,
            "score": snapshot.alignment_score,
            "score_parts": score_parts(snapshot, round),
            "verdict": round_verdict(snapshot, threshold, min_rounds, max_rounds),
            "artifacts": artifacts_for_round(snapshot, round),
            "directive": snapshot.expansion,
        }));
    }

    // Evidence: what the researcher actually retrieved, with similarity scores.
    // `seed_if_empty` writes to disk without refreshing the handle `prepare_run`
    // returned, so reopen the collection to see the seeded passages.
    let evidence_store = crate::kb::get_vector_store()?;
    let evidence_docs = retrieve_scored(&evidence_store, &topic, 5)?;

    let spans = recorder().span_records(Some(&run_id));
    let wall = recorder().wall_clock(Some(&run_id));
    let exclusive = recorder().exclusive_totals(Some(&run_id));

    let mut by_kind: Vec<Value> = exclusive
        .iter()
        .map(|(kind, seconds)| {
            let count = spans.iter().filter(|s| &s.kind == kind).count();
            json!({
                "kind": kind,
                "count": count,
                "seconds": round4(*seconds),
                "share": if wall > 0.0 { round4(seconds / wall * 100.0) } else { 0.0 },
            })
        })
        .collect();
    by_kind.sort_by(|a, b| {
        b["seconds"]
            .as_f64()
            .unwrap_or(0.0)
            .total_cmp(&a["seconds"].as_f64().unwrap_or(0.0))
    });

    let outcome = final_state.synthesis.as_ref().map(|synthesis| {
        let converged =
            synthesis.alignment_score >= threshold && synthesis.rounds_taken >= min_rounds;
        if converged {
            "converged"
        } else {
            "forced"
        }
    });

    Ok(json!({
        "schema_version": 1,
        "generated_at": crate::schemas::now().to_rfc3339(),
        "run_id": run_id,
        "source": {
            "kind": "replay",
            "scenario": scenario.get("name").cloned().unwrap_or(Value::Null),
            "note": "Recorded model output replayed through a local stub: the real agent code ran, the model was a recording.",
        },
        "topic": final_state.topic,
        "outcome": outcome,
        "config": {
            "values": start.config.values,
            "alignment_threshold": threshold,
            "min_rounds": min_rounds,
            "max_rounds": max_rounds,
            "arbiter_fallbacks": {
                "alignment_threshold": arbiter::ALIGNMENT_THRESHOLD,
                "min_rounds": arbiter::MIN_ROUNDS,
                "max_rounds": arbiter::MAX_ROUNDS,
            },
        },
        "providers": {
            "chat": crate::llm::resolve_provider(None, true)
                .map(|p| json!({"name": p.name, "default_model": p.default_model}))
                .unwrap_or(Value::Null),
            "embedding": crate::llm::resolve_embedding_provider(None)
                .map(|p| json!({"name": p.name, "model": crate::llm::embedding_model(p, None)}))
                .unwrap_or(Value::Null),
        },
        "formula": {
            "expression": "score = 0.80 x semantic_alignment + 0.20 x (1 - opposition_ratio)",
            "semantic_explanation": "How close this round's position is to earlier rounds' positions, averaged cosine similarity of the claim vectors.",
            "opposition_explanation": "The share of this round's challenges whose stance is oppose.",
            "resolution_note": "challenge_resolution_rate is recorded but not weighted: nothing in the code sets Challenge.resolved, so it would always be a constant.",
        },
        "rounds": rounds,
        "final": {
            "synthesis": final_state.synthesis,
            "rounds_taken": final_state.current_round,
            "alignment_score": final_state.alignment_score,
            "claims_total": final_state.claims.len(),
            "challenges_total": final_state.challenges.len(),
            "lateral_ideas_total": final_state.expansions.len(),
            "synthesis_attempts_total": final_state.syntheses.len(),
            "unresolved_challenges": final_state.challenges.iter().filter(|c| !c.resolved).count(),
        },
        "evidence": {
            "text": final_state.evidence,
            "documents": evidence_docs,
            "top_k": 5,
        },
        "telemetry": {
            "wall_clock_s": round4(wall),
            "spans": spans,
            "by_kind": by_kind,
        },
        "state_fields": state_field_inventory(),
    }))
}

/// Top-k passages with their cosine similarity to the topic.
fn retrieve_scored(
    store: &crate::kb::VectorStore,
    topic: &str,
    k: usize,
) -> Result<Vec<Value>, String> {
    Ok(store
        .similarity_search_scored(topic, k)?
        .into_iter()
        .map(|(score, doc)| json!({"id": doc.id, "text": doc.text, "similarity": round4(score)}))
        .collect())
}

/// Names of the scenarios available for replay, in fixture order.
pub fn scenario_names() -> Vec<String> {
    crate::devstub::fixture_scenarios()
        .iter()
        .filter_map(|s| s.get("name").and_then(|n| n.as_str()).map(String::from))
        .collect()
}

/// Replay one scenario by name.
pub fn replay_named(name: &str) -> Result<Value, String> {
    let scenarios = crate::devstub::fixture_scenarios();
    let scenario = scenarios
        .iter()
        .find(|s| s.get("name").and_then(|n| n.as_str()) == Some(name))
        .ok_or_else(|| {
            format!(
                "unknown scenario {:?}; available: {}",
                name,
                scenario_names().join(", ")
            )
        })?;
    replay_report(scenario)
}
