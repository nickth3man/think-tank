//! Synthesizer agent: merges perspectives, resolves contradictions.

use crate::llm::invoke_structured;
use crate::schemas::{
    now, Challenge, Claim, LateralIdea, SchemaKind, SynthesisAttempt, SynthesizerOutput,
};
use crate::state::ThinkTankState;
use crate::telemetry::span;

use super::prompts::SYNTHESIZER_SYSTEM_PROMPT;
use super::skeptic::truncate_chars;

pub const AGENT_ID: &str = "synthesizer";

/// Per-artefact character cap when rendering deliberation context.
pub const CONTENT_CHARS: usize = 400;

/// Compact one-line rendering of a claim's dimensions.
fn short_dimensions(dimensions: &crate::schemas::Dimensions) -> String {
    dimensions
        .iter()
        .take(4)
        .map(|(k, v)| format!("{}={}", k, truncate_chars(v, 40)))
        .collect::<Vec<_>>()
        .join(", ")
}

pub fn synthesizer_node(state: &ThinkTankState) -> Result<ThinkTankState, String> {
    span("synthesizer", "node", || synthesizer_node_body(state))
}

fn synthesizer_node_body(state: &ThinkTankState) -> Result<ThinkTankState, String> {
    let topic = &state.topic;
    let current_round = state.current_round;
    let config = &state.config;

    let current_claims: Vec<&Claim> = state
        .claims
        .iter()
        .filter(|c| c.round == current_round)
        .collect();
    let current_challenges: Vec<&Challenge> = state
        .challenges
        .iter()
        .filter(|ch| ch.round == current_round)
        .collect();
    let current_expansions: Vec<&LateralIdea> = state
        .expansions
        .iter()
        .filter(|e| e.round == current_round)
        .collect();

    // --- 1. Build context ---
    let mut context_parts: Vec<String> = vec![format!("## Topic\n{}", topic)];

    if !current_claims.is_empty() {
        let claim_lines: Vec<String> = current_claims
            .iter()
            .map(|c| {
                format!(
                    "- [{}] (ID: {}, {})\n  Dimensions: {}\n  {}",
                    c.agent_id,
                    c.id,
                    c.confidence,
                    short_dimensions(&c.dimensions),
                    truncate_chars(&c.content, CONTENT_CHARS)
                )
            })
            .collect();
        context_parts.push(format!("## Claims This Round\n{}", claim_lines.join("\n")));
    }

    if !current_challenges.is_empty() {
        let challenge_lines: Vec<String> = current_challenges
            .iter()
            .map(|ch| {
                format!(
                    "- [{} -> {}, {}] {}",
                    ch.agent_id,
                    truncate_chars(&ch.target_claim_id, 8),
                    ch.stance,
                    truncate_chars(&ch.content, CONTENT_CHARS)
                )
            })
            .collect();
        context_parts.push(format!(
            "## Challenges This Round\n{}",
            challenge_lines.join("\n")
        ));
    }

    if !current_expansions.is_empty() {
        let expansion_lines: Vec<String> = current_expansions
            .iter()
            .map(|e| {
                format!(
                    "- (ID: {}) {} | novelty: {}",
                    e.id,
                    truncate_chars(&e.content, CONTENT_CHARS),
                    truncate_chars(&e.novelty_rationale, 120)
                )
            })
            .collect();
        context_parts.push(format!(
            "## Lateral Ideas This Round\n{}",
            expansion_lines.join("\n")
        ));
    }

    if let Some(directive) = &state.expansion {
        context_parts.push(format!(
            "## Arbiter Directive\nFocus: {}\nDisagreement: {}",
            directive.focus_dimensions.join(", "),
            directive.disagreement_summary
        ));
    }

    let my_prior: Vec<&SynthesisAttempt> = state
        .syntheses
        .iter()
        .filter(|s| s.agent_id == AGENT_ID)
        .collect();
    if let Some(latest) = my_prior.last() {
        context_parts.push(format!(
            "## Your Prior Synthesis (round {})\n{}",
            latest.round,
            truncate_chars(&latest.content, 200)
        ));
        if !latest.remaining_tensions.is_empty() {
            let lines: Vec<String> = latest
                .remaining_tensions
                .iter()
                .map(|t| format!("- {}", t))
                .collect();
            context_parts.push(format!(
                "## Previously Unresolved Tensions\n{}",
                lines.join("\n")
            ));
        }
    }

    context_parts.push(format!(
        "## Current Round\n{}\n\nSynthesise all contributions above into a coherent merged perspective.",
        current_round
    ));

    let human_content = context_parts.join("\n\n");

    // --- 2. LLM call with structured output ---
    let raw = invoke_structured(
        AGENT_ID,
        config,
        SchemaKind::Synthesizer,
        SYNTHESIZER_SYSTEM_PROMPT,
        &human_content,
        0.2,
    )?;
    let output = SynthesizerOutput::parse(&raw)?;

    let attempt = SynthesisAttempt {
        id: crate::schemas::new_id(),
        agent_id: AGENT_ID.to_string(),
        round: current_round,
        content: output.content,
        incorporated_claim_ids: output.incorporated_claim_ids,
        resolved_tensions: output.resolved_tensions,
        remaining_tensions: output.remaining_tensions,
        confidence: output.confidence,
        created_at: now(),
    };

    let mut next = state.clone();
    next.syntheses.push(attempt);
    Ok(next)
}
