"""think_tank/agents/synthesizer.py — Synthesizer agent: merges perspectives, resolves contradictions."""

from __future__ import annotations

import typing as t

from langchain_core.messages import HumanMessage, SystemMessage

from think_tank.llm import agent_structured_llm
from think_tank.schemas import (
    Challenge,
    Claim,
    LateralIdea,
    SynthesisAttempt,
    SynthesizerOutput,
)
from think_tank.state import ThinkTankState
from think_tank.telemetry import span

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYNTHESIZER_SYSTEM_PROMPT = """\
You are the **Synthesizer** in a multi-agent Think Tank. Your job is to merge \
competing perspectives into a coherent whole and resolve contradictions.

## Behaviour
1. Review ALL claims, challenges, and lateral ideas from the current round.
2. Identify:
   - Points of **agreement** — where agents align.
   - Points of **contradiction** — where agents disagree.
   - Points of **complementarity** — where different perspectives fill each other's gaps.
3. Produce a synthesis that integrates the strongest elements of each contribution.
4. Be explicit about what you resolved, what you couldn't, and why.

## Synthesis Techniques
- **Higher abstraction**: Find a framework that subsumes apparently contradictory positions.
- **Conditional integration**: "X is true when [condition A], Y is true when [condition B]."
- **Sequential resolution**: "First do X (Researcher's evidence), then adapt with Y (Visionary's idea)."
- **Pragmatic weighting**: When positions conflict, favour the one with stronger evidence, \
lower risk, or higher leverage.

## Output Rules
- `content`: Your merged perspective, 80-130 words — the most useful, actionable \
output of the round, something a decision-maker could actually use.
- `incorporated_claim_ids`: IDs of every claim you drew from.
- `resolved_tensions`: The contradictions you resolved and how — one short \
sentence each, max 3 entries.
- `remaining_tensions`: Contradictions you could not resolve and why — one short \
sentence each, max 3 entries.
- `confidence`: Your confidence in this synthesis overall.

## Brevity (tokens cost wall-clock)
Completions are billed in latency: every extra 100 words costs ~0.5s. Write the minimum text that satisfies the rules above — no preamble, no restating the prompt, no meta-commentary, no bullet lists of everything you considered. Plain prose. Hit each length cap; never exceed it.

## Quality bar
- A good synthesis doesn't just average opinions — it finds the *right* integration.
- If agents genuinely disagree on facts, say so — don't paper over real conflicts.
- The synthesis should be more valuable than any single agent's contribution alone.
"""

# ---------------------------------------------------------------------------
# Node Function
# ---------------------------------------------------------------------------

_agent_id = "synthesizer"

#: Per-artefact character cap when rendering deliberation context.
CONTENT_CHARS = 400


def _short_dimensions(dimensions: dict[str, str]) -> str:
    """Compact one-line rendering of a claim's dimensions."""
    return ", ".join(f"{k}={v[:40]}" for k, v in list(dimensions.items())[:4])


def _synthesizer_node_body(state: ThinkTankState) -> dict:
    """
    LangGraph node: produces a SynthesisAttempt merging all round contributions.

    Flow:
        1. Read claims, challenges, and lateral ideas from the current round.
        2. Call the LLM with structured output -> SynthesizerOutput.
        3. Hydrate a full SynthesisAttempt and return a partial state update.
    """
    topic: str = state["topic"]
    current_round: int = state.get("current_round", 0)
    config: dict = state.get("config", {})
    existing_syntheses = state.get("syntheses", [])
    arbiter_directive = state.get("expansion")

    all_claims: list[Claim] = state.get("claims", [])
    current_claims = [c for c in all_claims if c.round == current_round]
    all_challenges: list[Challenge] = state.get("challenges", [])
    current_challenges = [ch for ch in all_challenges if ch.round == current_round]
    all_expansions: list[LateralIdea] = state.get("expansions", [])
    current_expansions = [e for e in all_expansions if e.round == current_round]

    # --- 1. Build context ---
    context_parts: list[str] = [f"## Topic\n{topic}"]

    if current_claims:
        claim_lines = [
            f"- [{c.agent_id}] (ID: {c.id}, {c.confidence.value})\n"
            f"  Dimensions: {_short_dimensions(c.dimensions)}\n"
            f"  {c.content[:CONTENT_CHARS]}"
            for c in current_claims
        ]
        context_parts.append("## Claims This Round\n" + "\n".join(claim_lines))

    if current_challenges:
        challenge_lines = [
            f"- [{ch.agent_id} -> {ch.target_claim_id[:8]}, {ch.stance.value}] "
            f"{ch.content[:CONTENT_CHARS]}"
            for ch in current_challenges
        ]
        context_parts.append("## Challenges This Round\n" + "\n".join(challenge_lines))

    if current_expansions:
        expansion_lines = [
            f"- (ID: {e.id}) {e.content[:CONTENT_CHARS]} | novelty: {e.novelty_rationale[:120]}"
            for e in current_expansions
        ]
        context_parts.append("## Lateral Ideas This Round\n" + "\n".join(expansion_lines))

    if arbiter_directive is not None:
        context_parts.append(
            f"## Arbiter Directive\n"
            f"Focus: {', '.join(arbiter_directive.focus_dimensions)}\n"
            f"Disagreement: {arbiter_directive.disagreement_summary}"
        )

    # Prior synthesis attempts for continuity
    my_prior = [s for s in existing_syntheses if s.agent_id == _agent_id]
    if my_prior:
        latest = my_prior[-1]
        context_parts.append(
            f"## Your Prior Synthesis (round {latest.round})\n{latest.content[:200]}"
        )
        if latest.remaining_tensions:
            context_parts.append(
                "## Previously Unresolved Tensions\n"
                + "\n".join(f"- {t}" for t in latest.remaining_tensions)
            )

    context_parts.append(
        f"## Current Round\n{current_round}\n\n"
        "Synthesise all contributions above into a coherent merged perspective."
    )

    human_content = "\n\n".join(context_parts)

    # --- 2. LLM call with structured output ---
    structured_llm = agent_structured_llm(_agent_id, config, SynthesizerOutput, temperature=0.2)

    output = t.cast(
        SynthesizerOutput,
        structured_llm.invoke(
            [
                SystemMessage(content=SYNTHESIZER_SYSTEM_PROMPT),
                HumanMessage(content=human_content),
            ]
        ),
    )

    # --- 3. Hydrate full SynthesisAttempt ---
    attempt = SynthesisAttempt(
        agent_id=_agent_id,
        round=current_round,
        content=output.content,
        incorporated_claim_ids=output.incorporated_claim_ids,
        resolved_tensions=output.resolved_tensions,
        remaining_tensions=output.remaining_tensions,
        confidence=output.confidence,
    )

    return {"syntheses": [*existing_syntheses, attempt]}


def synthesizer_node(state: ThinkTankState) -> dict:
    """Instrumented wrapper: records latency for the whole agent node."""
    with span("synthesizer", "node", round=state.get("current_round", 0)):
        return _synthesizer_node_body(state)
