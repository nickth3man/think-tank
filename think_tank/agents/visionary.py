"""think_tank/agents/visionary.py — Visionary agent: proposes unconventional lateral ideas."""

from __future__ import annotations

import os
import typing as t

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openrouter import ChatOpenRouter

from think_tank.schemas import Challenge, Claim, LateralIdea, VisionaryOutput
from think_tank.state import ThinkTankState

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

VISIONARY_SYSTEM_PROMPT = """\
You are the **Visionary** in a multi-agent Think Tank. Your job is to expand \
the solution space by proposing unconventional, lateral ideas that others \
haven't considered.

## Behaviour
1. Review the current claims and challenges to understand the debate landscape.
2. Look for hidden assumptions, unexplored analogies, or unexpected re-combinations.
3. Propose **one** lateral idea that is surprising yet plausible — not reckless.
4. Explain how your idea connects to or departs from existing claims.

## Thinking Techniques (use as appropriate)
- **Analogy**: "What if we solved this the way [unrelated domain] handles [similar problem]?"
- **Inversion**: "What if the opposite of the conventional approach were true?"
- **Recombination**: "What if we combined approach X from claim A with approach Y from claim B?"
- **Scale shift**: "What if this were 10x bigger/smaller/faster/cheaper?"
- **Constraint removal**: "What if [key constraint] didn't exist?"

## Output Rules
- `content`: Your lateral idea (≥ 50 words). Be specific and actionable — vague \
hand-waving is not helpful.
- `related_claim_ids`: IDs of claims your idea builds on or responds to.
- `novelty_rationale`: Explain why this idea is non-obvious AND why it could work \
despite being unconventional.

## Quality bar
- Surprising ≠ absurd. Your idea must be defensible with at least one concrete argument.
- Avoid pure speculation — ground creativity in something real (an analogy, a precedent, \
a structural insight).
"""

# ---------------------------------------------------------------------------
# Node Function
# ---------------------------------------------------------------------------

_agent_id = "visionary"


def visionary_node(state: ThinkTankState) -> dict:
    """
    LangGraph node: produces a LateralIdea that expands the solution space.

    Flow:
        1. Read claims and challenges from the current round.
        2. Call the LLM with structured output → VisionaryOutput.
        3. Hydrate a full LateralIdea and return a partial state update.
    """
    topic: str = state["topic"]
    current_round: int = state.get("current_round", 0)
    config: dict = state.get("config", {})
    existing_expansions = state.get("expansions", [])
    arbiter_directive = state.get("expansion")

    all_claims: list[Claim] = state.get("claims", [])
    current_claims = [c for c in all_claims if c.round == current_round]
    all_challenges: list[Challenge] = state.get("challenges", [])
    current_challenges = [ch for ch in all_challenges if ch.round == current_round]

    # --- 1. Build context ---
    context_parts: list[str] = [f"## Topic\n{topic}"]

    if current_claims:
        claim_lines = [
            f"- [{c.agent_id}] (ID: {c.id}) {c.content}"
            for c in current_claims
        ]
        context_parts.append("## Current Claims\n" + "\n".join(claim_lines))

    if current_challenges:
        challenge_lines = [
            f"- [{ch.agent_id} → {ch.stance.value}] {ch.content[:200]}"
            for ch in current_challenges
        ]
        context_parts.append("## Current Challenges\n" + "\n".join(challenge_lines))

    if arbiter_directive is not None:
        context_parts.append(
            f"## Arbiter Directive\n"
            f"Focus: {', '.join(arbiter_directive.focus_dimensions)}\n"
            f"Disagreement: {arbiter_directive.disagreement_summary}"
        )

    # Show our prior ideas for continuity (avoid repeating)
    my_prior = [e for e in existing_expansions if e.agent_id == _agent_id]
    if my_prior:
        lines = [f"- {e.content[:150]}" for e in my_prior[-2:]]
        context_parts.append("## Your Prior Ideas (do not repeat)\n" + "\n".join(lines))

    context_parts.append(
        f"## Current Round\n{current_round}\n\n"
        "Propose a lateral idea that goes beyond what has already been stated."
    )

    human_content = "\n\n".join(context_parts)

    # --- 2. LLM call with structured output ---
    model_name = config.get("visionary_model", os.getenv("DEFAULT_CHAT_MODEL", "openai/gpt-4o-mini"))
    llm = ChatOpenRouter(model=model_name, temperature=0.7)  # higher temp for creativity
    structured_llm = llm.with_structured_output(VisionaryOutput, method="json_schema")

    output = t.cast(VisionaryOutput, structured_llm.invoke([
        SystemMessage(content=VISIONARY_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]))

    # --- 3. Hydrate full LateralIdea ---
    idea = LateralIdea(
        agent_id=_agent_id,
        round=current_round,
        content=output.content,
        related_claim_ids=output.related_claim_ids,
        novelty_rationale=output.novelty_rationale,
    )

    return {"expansions": existing_expansions + [idea]}
