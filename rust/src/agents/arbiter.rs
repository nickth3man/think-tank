//! Arbiter node + routing, mirroring `think_tank/agents/arbiter.py`.
//!
//! The arbiter makes no LLM calls. Its score is
//! `0.80 × semantic + 0.20 × (1 − opposition ratio)`, where semantic alignment
//! compares this round's claim embeddings with prior rounds' — i.e. whether the
//! position has stabilised.

use std::collections::BTreeMap;

use crate::schemas::{now, Challenge, Claim, Expansion, Stance, Synthesis};
use crate::state::ThinkTankState;
use crate::telemetry::span_attrs;

// Module-level fallbacks; the defaults that actually apply live in
// `runner::DEFAULT_CONFIG`.
pub const ALIGNMENT_THRESHOLD: f64 = 0.75;
pub const MIN_ROUNDS: u32 = 2;
pub const MAX_ROUNDS: u32 = 6;

/// Cosine similarity between two equal-length vectors.
pub fn cosine_similarity(a: &[f64], b: &[f64]) -> f64 {
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

/// Semantic agreement across agents *and* across rounds.
///
/// Only the researcher emits `Claim`s, so comparing a round's claims with each
/// other always saw a single claim. Comparing each current claim with the
/// previous rounds' claims measures whether the position has stabilised, which
/// is what convergence means here.
pub fn pairwise_alignment(claims: &[&Claim], prior_claims: &[&Claim]) -> f64 {
    let mut scores: Vec<f64> = Vec::new();
    for i in 0..claims.len() {
        for j in (i + 1)..claims.len() {
            scores.push(cosine_similarity(
                &claims[i].embedding,
                &claims[j].embedding,
            ));
        }
    }
    if !claims.is_empty() && !prior_claims.is_empty() {
        for c in claims {
            for p in prior_claims {
                scores.push(cosine_similarity(&c.embedding, &p.embedding));
            }
        }
    }
    if scores.is_empty() {
        // Nothing to compare yet (first round, one claim) -> neutral, not aligned.
        return 0.0;
    }
    scores.iter().sum::<f64>() / scores.len() as f64
}

/// Fraction of challenges that have been resolved (accepted).
pub fn challenge_resolution_rate(challenges: &[&Challenge]) -> f64 {
    if challenges.is_empty() {
        return 1.0;
    }
    let resolved = challenges.iter().filter(|c| c.resolved).count();
    resolved as f64 / challenges.len() as f64
}

/// Fraction of challenges that are OPPOSE stance — lower is better for convergence.
pub fn opposition_ratio(challenges: &[&Challenge]) -> f64 {
    if challenges.is_empty() {
        return 0.0;
    }
    let opposed = challenges
        .iter()
        .filter(|c| c.stance == Stance::Oppose)
        .count();
    opposed as f64 / challenges.len() as f64
}

/// Dimensions where agents disagree most (heuristic: most unique values).
pub fn find_weak_dimensions(claims: &[&Claim]) -> Vec<String> {
    if claims.is_empty() {
        return Vec::new();
    }
    let mut distinct: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut order: Vec<String> = Vec::new();
    for claim in claims {
        for (dim, value) in claim.dimensions.iter() {
            let entry = distinct.entry(dim.clone()).or_insert_with(|| {
                order.push(dim.clone());
                Vec::new()
            });
            if !entry.contains(value) {
                entry.push(value.clone());
            }
        }
    }
    let mut ranked: Vec<(String, usize)> = order
        .into_iter()
        .map(|dim| {
            let count = distinct.get(&dim).map(|v| v.len()).unwrap_or(0);
            (dim, count)
        })
        .collect();
    // Stable sort by distinct count descending, preserving first-seen order
    // for ties, matching Python's `sorted(..., reverse=True)`.
    ranked.sort_by_key(|(_, count)| std::cmp::Reverse(*count));
    ranked
        .into_iter()
        .filter(|(_, count)| *count > 1)
        .take(3)
        .map(|(dim, _)| dim)
        .collect()
}

/// Evaluates agent alignment and produces either an Expansion (route back to
/// agents) or a Synthesis (route to END).
pub fn arbiter_node(state: &ThinkTankState) -> Result<ThinkTankState, String> {
    let current_round = state.current_round;
    let topic = &state.topic;
    let config = &state.config;

    let threshold = config
        .get("alignment_threshold")
        .and_then(|v| v.parse().ok())
        .unwrap_or(ALIGNMENT_THRESHOLD);
    let min_rounds = config.min_rounds_or(MIN_ROUNDS);
    let max_rounds = config.max_rounds_or(MAX_ROUNDS);

    let latest_claims: Vec<&Claim> = state
        .claims
        .iter()
        .filter(|c| c.round == current_round)
        .collect();
    let latest_challenges: Vec<&Challenge> = state
        .challenges
        .iter()
        .filter(|c| c.round == current_round)
        .collect();
    let prior_claims: Vec<&Claim> = state
        .claims
        .iter()
        .filter(|c| c.round < current_round)
        .collect();

    let semantic_alignment = pairwise_alignment(&latest_claims, &prior_claims);
    let resolution_rate = challenge_resolution_rate(&latest_challenges);
    let opposition = opposition_ratio(&latest_challenges);

    // Weight only the terms that carry information; the resolution rate is
    // recorded on the span so the day a producer starts setting `resolved` it
    // is visible immediately.
    let raw_score = 0.80 * semantic_alignment + 0.20 * (1.0 - opposition);
    let alignment_score = round4(raw_score.clamp(0.0, 1.0));

    span_attrs(
        "arbiter.score",
        "arbiter",
        &[
            ("round", current_round.to_string()),
            ("claims", latest_claims.len().to_string()),
            ("challenges", latest_challenges.len().to_string()),
            ("semantic", round4(semantic_alignment).to_string()),
            ("resolution", round4(resolution_rate).to_string()),
            ("opposition", round4(opposition).to_string()),
            ("score", alignment_score.to_string()),
            ("threshold", threshold.to_string()),
        ],
        || {},
    );

    // `current_round` is the 0-based index of the round just completed, so the
    // number of rounds run so far is `current_round + 1`.
    let rounds_completed = current_round + 1;
    let converged = alignment_score >= threshold && rounds_completed >= min_rounds;
    let forced_end = rounds_completed >= max_rounds;

    let mut next = state.clone();
    if converged || forced_end {
        let verdict = if forced_end && !converged {
            "forced"
        } else {
            "natural"
        };
        // The Synthesizer already produced an LLM-merged answer for this round.
        let latest_attempt = state
            .syntheses
            .iter()
            .rev()
            .find(|s| s.round == current_round);
        let synthesis_content = match latest_attempt {
            Some(attempt) => {
                let mut content = attempt.content.clone();
                if !attempt.remaining_tensions.is_empty() {
                    content.push_str("\n\nRemaining tensions:\n");
                    content.push_str(
                        &attempt
                            .remaining_tensions
                            .iter()
                            .map(|t| format!("- {}", t))
                            .collect::<Vec<_>>()
                            .join("\n"),
                    );
                }
                content
            }
            None => build_synthesis_content(topic, &latest_claims, &state.challenges, verdict),
        };
        let synthesis = Synthesis {
            id: crate::schemas::new_id(),
            content: synthesis_content,
            contributing_claim_ids: latest_claims.iter().map(|c| c.id.clone()).collect(),
            alignment_score,
            rounds_taken: current_round + 1,
            unresolved_challenges: state
                .challenges
                .iter()
                .filter(|c| !c.resolved)
                .map(|c| c.id.clone())
                .collect(),
            created_at: now(),
        };
        next.alignment_score = alignment_score;
        next.synthesis = Some(synthesis);
        next.expansion = None;
        next.current_round = current_round + 1;
    } else {
        let mut weak_dims = find_weak_dimensions(&latest_claims);
        if weak_dims.is_empty() {
            weak_dims = vec!["overall reasoning".to_string()];
        }
        let expansion = Expansion {
            id: crate::schemas::new_id(),
            round: current_round + 1,
            prompt: format!(
                "The group has not yet aligned on: {}. Current alignment is {:.2} (target: {}). \
                 Please refine your position, addressing the strongest objections from other agents.",
                weak_dims.join(", "),
                alignment_score,
                threshold
            ),
            focus_dimensions: weak_dims,
            disagreement_summary: summarize_disagreement(&latest_claims, &state.challenges),
            created_at: now(),
        };
        next.alignment_score = alignment_score;
        next.expansion = Some(expansion);
        next.synthesis = None;
        next.current_round = current_round + 1;
    }
    Ok(next)
}

/// Python's `round(x, 4)`, which uses correctly-rounded decimal formatting.
fn round4(value: f64) -> f64 {
    format!("{:.4}", value).parse().unwrap_or(value)
}

/// Deterministic fallback when no Synthesizer attempt is available.
fn build_synthesis_content(
    topic: &str,
    claims: &[&Claim],
    _challenges: &[Challenge],
    verdict: &str,
) -> String {
    let prefix = if verdict == "natural" {
        "Convergence reached. "
    } else {
        "Max rounds reached — best-effort synthesis. "
    };
    let positions = claims
        .iter()
        .map(|c| {
            format!(
                "- Agent {} ({} confidence): {}",
                c.agent_id, c.confidence, c.content
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    format!("{}Topic: {}\n\nPositions:\n{}", prefix, topic, positions)
}

/// Brief human-readable summary of where agents diverge.
fn summarize_disagreement(claims: &[&Claim], challenges: &[Challenge]) -> String {
    let _ = claims;
    if challenges.is_empty() {
        return "No explicit challenges raised yet — agents may be implicitly misaligned."
            .to_string();
    }
    let active: Vec<&Challenge> = challenges.iter().filter(|c| !c.resolved).collect();
    if active.is_empty() {
        return "All challenges resolved — alignment should be high.".to_string();
    }
    let lines: Vec<String> = active
        .iter()
        .take(5)
        .map(|c| {
            format!(
                "{} -> claim {}... ({}): {}",
                c.agent_id,
                c.target_claim_id.chars().take(8).collect::<String>(),
                c.stance,
                c.content.chars().take(120).collect::<String>()
            )
        })
        .collect();
    format!("Unresolved challenges:\n{}", lines.join("\n"))
}

/// Called after the arbiter node runs: the next node, or END.
pub fn route_after_arbiter(state: &ThinkTankState) -> Route {
    if state.synthesis.is_some() {
        Route::End
    } else {
        Route::Researcher
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Route {
    Researcher,
    End,
}
