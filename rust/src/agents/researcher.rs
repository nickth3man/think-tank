//! Researcher agent: grounds discussion in evidence.

use crate::kb::retrieve;
use crate::llm::{embed_query, invoke_structured};
use crate::schemas::{now, Claim, ResearcherOutput, SchemaKind};
use crate::state::ThinkTankState;
use crate::telemetry::span;

use super::prompts::RESEARCHER_SYSTEM_PROMPT;

pub const AGENT_ID: &str = "researcher";

pub fn researcher_node(state: &ThinkTankState) -> Result<ThinkTankState, String> {
    span("researcher", "node", || researcher_node_body(state))
}

fn researcher_node_body(state: &ThinkTankState) -> Result<ThinkTankState, String> {
    let topic = &state.topic;
    let current_round = state.current_round;
    let config = &state.config;

    // --- 1. Build deliberation context ---
    let mut context_parts: Vec<String> = vec![format!("## Topic\n{}", topic)];

    // The topic does not change between rounds, so the retrieval is stored in
    // run state on the first round rather than re-queried every round.
    let evidence = if state.evidence.is_empty() {
        retrieve(topic, 5)?
    } else {
        state.evidence.clone()
    };
    context_parts.push(format!("## Evidence Excerpts\n{}", evidence));

    if current_round > 0 {
        let prior_claims: Vec<&Claim> = state
            .claims
            .iter()
            .filter(|c| c.round < current_round)
            .collect();
        if !prior_claims.is_empty() {
            let start = prior_claims.len().saturating_sub(6);
            let lines: Vec<String> = prior_claims[start..]
                .iter()
                .map(|c| {
                    format!(
                        "- [{}] (round {}, {}): {}",
                        c.agent_id, c.round, c.confidence, c.content
                    )
                })
                .collect();
            context_parts.push(format!("## Prior Claims\n{}", lines.join("\n")));
        }

        let my_ids: Vec<&str> = state
            .claims
            .iter()
            .filter(|c| c.agent_id == AGENT_ID)
            .map(|c| c.id.as_str())
            .collect();
        let active_challenges: Vec<_> = state
            .challenges
            .iter()
            .filter(|ch| my_ids.contains(&ch.target_claim_id.as_str()) && !ch.resolved)
            .collect();
        if !active_challenges.is_empty() {
            let start = active_challenges.len().saturating_sub(4);
            let lines: Vec<String> = active_challenges[start..]
                .iter()
                .map(|ch| format!("- [{}] {}", ch.stance, ch.content))
                .collect();
            context_parts.push(format!(
                "## Challenges to Your Prior Claims\n{}",
                lines.join("\n")
            ));
        }
    }

    if let Some(directive) = &state.expansion {
        context_parts.push(format!(
            "## Arbiter Directive (round {})\nFocus areas: {}\nDisagreement: {}\nInstruction: {}",
            directive.round,
            directive.focus_dimensions.join(", "),
            directive.disagreement_summary,
            directive.prompt
        ));
    }

    context_parts.push(format!("## Current Round\n{}", current_round));

    let human_content = context_parts.join("\n\n");

    // --- 3. LLM call with structured output ---
    let raw = invoke_structured(
        AGENT_ID,
        config,
        SchemaKind::Researcher,
        RESEARCHER_SYSTEM_PROMPT,
        &human_content,
        0.2,
    )?;
    let output = ResearcherOutput::parse(&raw)?;

    let claim_embedding = embed_query(&output.content)?;

    let claim = Claim {
        id: crate::schemas::new_id(),
        agent_id: AGENT_ID.to_string(),
        round: current_round,
        content: output.content,
        dimensions: output.dimensions,
        confidence: output.confidence,
        evidence_summary: output.evidence_summary,
        embedding: claim_embedding,
        created_at: now(),
    };

    let mut next = state.clone();
    next.evidence = evidence;
    next.claims.push(claim);
    Ok(next)
}
