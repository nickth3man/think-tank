"""think_tank/agents/skeptic.py — Skeptic agent: stress-tests claims with structured challenges."""

from __future__ import annotations

import os
import typing as t

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openrouter import ChatOpenRouter

from think_tank.schemas import Challenge, Claim, SkepticOutput
from think_tank.state import ThinkTankState

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SKEPTIC_SYSTEM_PROMPT = """\
You are the **Skeptic** in a multi-agent Think Tank. Your job is to stress-test \
claims, expose hidden assumptions, and surface the strongest counter-arguments.

## Behaviour
1. Review every claim produced in the current round by other agents.
2. Identify the claim with the weakest justification, largest logical gap, or \
highest-stakes implications.
3. Produce a single, targeted Challenge against that claim.
4. Choose your stance carefully:
   - **OPPOSE** — the claim is flawed or the evidence is insufficient.
   - **REFINE** — the claim is directionally right but needs qualification or \
narrower scope.
   - **SUPPORT** — the claim is strong but an important nuance or caveat is missing.

## Output Rules
- `target_claim_id`: Must exactly match a claim ID from the current round.
- `content`: A precise, substantive challenge (≥ 50 words). No ad-hominem, no \
trivial nitpicks — focus on the most impactful weakness.
- `reasoning`: Explain your logic or cite counter-evidence.
- `stance`: Choose the stance that best represents your assessment.

## Anti-patterns to avoid
- Do not challenge every claim equally — pick the **one** that most needs scrutiny.
- Do not merely summarise a claim and say "I agree" — add substantive value.
- Do not attack the agent; attack the argument.
"""

# ---------------------------------------------------------------------------
# Node Function
# ---------------------------------------------------------------------------

_agent_id = "skeptic"


def skeptic_node(state: ThinkTankState) -> dict:
    """
    LangGraph node: produces a structured Challenge targeting a specific claim.

    Flow:
        1. Read claims from the current round.
        2. Call the LLM with structured output -> SkepticOutput.
        3. Hydrate a full Challenge and return a partial state update.
    """
    topic: str = state["topic"]
    current_round: int = state.get("current_round", 0)
    config: dict = state.get("config", {})
    existing_challenges = state.get("challenges", [])
    arbiter_directive = state.get("expansion")

    # --- 1. Gather current-round claims (produced by agents before us) ---
    all_claims: list[Claim] = state.get("claims", [])
    current_claims = [c for c in all_claims if c.round == current_round]

    if not current_claims:
        # Nothing to challenge — return an empty update
        return {}

    # --- 2. Build context for the LLM ---
    context_parts: list[str] = [f"## Topic\n{topic}"]

    # Present current-round claims with their IDs so the LLM can target one
    claim_lines = [
        f"### Claim ID: {c.id}\n"
        f"Agent: {c.agent_id} | Confidence: {c.confidence.value}\n"
        f"Dimensions: {c.dimensions}\n"
        f"Content: {c.content}"
        for c in current_claims
    ]
    context_parts.append("## Claims to Scrutinise\n" + "\n\n".join(claim_lines))

    # Show prior challenges we've raised (for continuity)
    my_prior_challenges = [
        ch for ch in existing_challenges if ch.agent_id == _agent_id and ch.round < current_round
    ]
    if my_prior_challenges:
        lines = [f"- ({ch.stance.value}) {ch.content[:150]}" for ch in my_prior_challenges[-3:]]
        context_parts.append("## Your Prior Challenges\n" + "\n".join(lines))

    if arbiter_directive is not None:
        context_parts.append(
            f"## Arbiter Directive\n"
            f"Focus: {', '.join(arbiter_directive.focus_dimensions)}\n"
            f"Disagreement: {arbiter_directive.disagreement_summary}"
        )

    context_parts.append(
        f"## Current Round\n{current_round}\n\n"
        "Select the ONE claim that most needs scrutiny and produce your challenge."
    )

    human_content = "\n\n".join(context_parts)

    # --- 3. LLM call with structured output ---
    model_name = config.get("skeptic_model", os.getenv("DEFAULT_CHAT_MODEL", "openai/gpt-4o-mini"))
    llm = ChatOpenRouter(model=model_name, temperature=0.3)
    structured_llm = llm.with_structured_output(SkepticOutput, method="json_schema")
    output = t.cast(
        SkepticOutput,
        structured_llm.invoke(
            [
                SystemMessage(content=SKEPTIC_SYSTEM_PROMPT),
                HumanMessage(content=human_content),
            ]
        ),
    )

    # --- 4. Hydrate the full Challenge ---
    challenge = Challenge(
        agent_id=_agent_id,
        target_claim_id=output.target_claim_id,
        round=current_round,
        stance=output.stance,
        content=output.content,
        reasoning=output.reasoning,
    )

    return {"challenges": [*existing_challenges, challenge]}
