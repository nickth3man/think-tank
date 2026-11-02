//! Skeptic agent: stress-tests claims with structured challenges.

use crate::llm::invoke_structured;
use crate::schemas::{now, Challenge, Claim, SchemaKind, SkepticOutput};
use crate::state::ThinkTankState;
use crate::telemetry::span;

use super::prompts::SKEPTIC_SYSTEM_PROMPT;

pub const AGENT_ID: &str = "skeptic";

pub fn skeptic_node(state: &ThinkTankState) -> Result<ThinkTankState, String> {
    span("skeptic", "node", || skeptic_node_body(state))
}

fn skeptic_node_body(state: &ThinkTankState) -> Result<ThinkTankState, String> {
    let topic = &state.topic;
    let current_round = state.current_round;
    let config = &state.config;

    let current_claims: Vec<&Claim> = state
        .claims
        .iter()
        .filter(|c| c.round == current_round)
        .collect();

    if current_claims.is_empty() {
        // Nothing to challenge — return an unchanged state.
        return Ok(state.clone());
    }

    // --- 2. Build context for the LLM ---
    let mut context_parts: Vec<String> = vec![format!("## Topic\n{}", topic)];

    let claim_lines: Vec<String> = current_claims
        .iter()
        .map(|c| {
            format!(
                "### Claim ID: {}\nAgent: {} | Confidence: {}\nDimensions: {}\nContent: {}",
                c.id, c.agent_id, c.confidence, c.dimensions, c.content
            )
        })
        .collect();
    context_parts.push(format!(
        "## Claims to Scrutinise\n{}",
        claim_lines.join("\n\n")
    ));

    let my_prior: Vec<_> = state
        .challenges
        .iter()
        .filter(|ch| ch.agent_id == AGENT_ID && ch.round < current_round)
        .collect();
    if !my_prior.is_empty() {
        let start = my_prior.len().saturating_sub(3);
        let lines: Vec<String> = my_prior[start..]
            .iter()
            .map(|ch| format!("- ({}) {}", ch.stance, truncate_chars(&ch.content, 150)))
            .collect();
        context_parts.push(format!("## Your Prior Challenges\n{}", lines.join("\n")));
    }

    if let Some(directive) = &state.expansion {
        context_parts.push(format!(
            "## Arbiter Directive\nFocus: {}\nDisagreement: {}",
            directive.focus_dimensions.join(", "),
            directive.disagreement_summary
        ));
    }

    context_parts.push(format!(
        "## Current Round\n{}\n\nSelect the ONE claim that most needs scrutiny and produce your challenge.",
        current_round
    ));

    let human_content = context_parts.join("\n\n");

    // --- 3. LLM call with structured output ---
    let raw = invoke_structured(
        AGENT_ID,
        config,
        SchemaKind::Skeptic,
        SKEPTIC_SYSTEM_PROMPT,
        &human_content,
        0.3,
    )?;
    let output = SkepticOutput::parse(&raw)?;

    let challenge = Challenge {
        id: crate::schemas::new_id(),
        agent_id: AGENT_ID.to_string(),
        target_claim_id: output.target_claim_id,
        round: current_round,
        stance: output.stance,
        content: output.content,
        reasoning: output.reasoning,
        resolved: false,
        created_at: now(),
    };

    let mut next = state.clone();
    next.challenges.push(challenge);
    Ok(next)
}

/// Python's `s[:n]` — a character slice, not a byte slice.
pub fn truncate_chars(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}
