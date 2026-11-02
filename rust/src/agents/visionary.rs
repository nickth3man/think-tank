//! Visionary agent: proposes unconventional lateral ideas.

use crate::llm::invoke_structured;
use crate::schemas::{now, Challenge, Claim, LateralIdea, SchemaKind, VisionaryOutput};
use crate::state::ThinkTankState;
use crate::telemetry::span;

use super::prompts::VISIONARY_SYSTEM_PROMPT;
use super::skeptic::truncate_chars;

pub const AGENT_ID: &str = "visionary";

/// Per-artefact character cap when rendering deliberation context.
pub const CONTENT_CHARS: usize = 300;

pub fn visionary_node(state: &ThinkTankState) -> Result<ThinkTankState, String> {
    span("visionary", "node", || visionary_node_body(state))
}

fn visionary_node_body(state: &ThinkTankState) -> Result<ThinkTankState, String> {
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

    // --- 1. Build context ---
    let mut context_parts: Vec<String> = vec![format!("## Topic\n{}", topic)];

    if !current_claims.is_empty() {
        let claim_lines: Vec<String> = current_claims
            .iter()
            .map(|c| {
                format!(
                    "- [{}] (ID: {}) {}",
                    c.agent_id,
                    c.id,
                    truncate_chars(&c.content, CONTENT_CHARS)
                )
            })
            .collect();
        context_parts.push(format!("## Current Claims\n{}", claim_lines.join("\n")));
    }

    if !current_challenges.is_empty() {
        let challenge_lines: Vec<String> = current_challenges
            .iter()
            .map(|ch| {
                format!(
                    "- [{} -> {}] {}",
                    ch.agent_id,
                    ch.stance,
                    truncate_chars(&ch.content, 150)
                )
            })
            .collect();
        context_parts.push(format!(
            "## Current Challenges\n{}",
            challenge_lines.join("\n")
        ));
    }

    if let Some(directive) = &state.expansion {
        context_parts.push(format!(
            "## Arbiter Directive\nFocus: {}\nDisagreement: {}",
            directive.focus_dimensions.join(", "),
            directive.disagreement_summary
        ));
    }

    let my_prior: Vec<&LateralIdea> = state
        .expansions
        .iter()
        .filter(|e| e.agent_id == AGENT_ID)
        .collect();
    if !my_prior.is_empty() {
        let start = my_prior.len().saturating_sub(2);
        let lines: Vec<String> = my_prior[start..]
            .iter()
            .map(|e| format!("- {}", truncate_chars(&e.content, 120)))
            .collect();
        context_parts.push(format!(
            "## Your Prior Ideas (do not repeat)\n{}",
            lines.join("\n")
        ));
    }

    context_parts.push(format!(
        "## Current Round\n{}\n\nPropose a lateral idea that goes beyond what has already been stated.",
        current_round
    ));

    let human_content = context_parts.join("\n\n");

    // --- 2. LLM call with structured output (higher temp for creativity) ---
    let raw = invoke_structured(
        AGENT_ID,
        config,
        SchemaKind::Visionary,
        VISIONARY_SYSTEM_PROMPT,
        &human_content,
        0.7,
    )?;
    let output = VisionaryOutput::parse(&raw)?;

    let idea = LateralIdea {
        id: crate::schemas::new_id(),
        agent_id: AGENT_ID.to_string(),
        round: current_round,
        content: output.content,
        related_claim_ids: output.related_claim_ids,
        novelty_rationale: output.novelty_rationale,
        created_at: now(),
    };

    let mut next = state.clone();
    next.expansions.push(idea);
    Ok(next)
}
