"""think_tank/agents/researcher.py — Researcher agent: grounds discussion in evidence."""

from __future__ import annotations

import typing as t

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import OpenAIEmbeddings

from think_tank.kb import retrieve
from think_tank.llm import agent_structured_llm, get_embeddings
from think_tank.schemas import Claim, ResearcherOutput
from think_tank.state import ThinkTankState
from think_tank.telemetry import span

_embedder = None


def _get_embedder() -> OpenAIEmbeddings:
    global _embedder
    if _embedder is None:
        _embedder = get_embeddings()
    return _embedder


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

RESEARCHER_SYSTEM_PROMPT = """\
You are the **Researcher** in a multi-agent Think Tank. Your job is to ground \
the discussion in verifiable facts and evidence retrieved from a knowledge base.

## Behaviour
1. Analyse the topic and any prior-round deliberation context you receive.
2. Rely **only** on the provided evidence excerpts — do not fabricate citations.
3. Produce a single, well-sourced Claim that reflects the strongest evidence-based \
position you can construct.
4. Acknowledge gaps or limitations in the available evidence honestly.

## Output Rules
- `content`: Your claim, 50-90 words, backed by evidence.
- `dimensions`: Exactly 3 aspects, each a short phrase (<= 12 words), e.g. \
{"feasibility": "high", "risk": "moderate", "impact": "high"}.
- `confidence`: Rate honestly — LOW if evidence is thin, HIGH only when well-supported.
- `evidence_summary`: One sentence (<= 30 words) on the key supporting evidence.

## Brevity (tokens cost wall-clock)
Completions are billed in latency: every extra 100 words costs ~0.5s. Write the minimum text that satisfies the rules above — no preamble, no restating the prompt, no meta-commentary, no bullet lists of everything you considered. Plain prose. Hit each length cap; never exceed it.
"""

# ---------------------------------------------------------------------------
# Node Function
# ---------------------------------------------------------------------------

_agent_id = "researcher"


def _researcher_node_body(state: ThinkTankState) -> dict:
    """
    LangGraph node: produces an evidence-grounded Claim.

    Flow:
        1. Read topic, round, and any arbiter expansion directive.
        2. Retrieve relevant documents from the vector knowledge base.
        3. Call the LLM with structured output -> ResearcherOutput.
        4. Hydrate a full Claim and return a partial state update.
    """
    topic: str = state["topic"]
    current_round: int = state.get("current_round", 0)
    config: dict = state.get("config", {})
    existing_claims: list[Claim] = state.get("claims", [])
    existing_challenges = state.get("challenges", [])
    arbiter_directive = state.get("expansion")  # Arbiter's Expansion | None

    # --- 1. Build deliberation context ---
    context_parts: list[str] = [f"## Topic\n{topic}"]

    # Ground the claim in the knowledge base. Without this the Researcher has
    # nothing but the topic and correctly refuses to make an evidential claim.
    # The topic does not change between rounds, so the retrieval is stored in
    # run state on the first round rather than re-queried every round.
    evidence = state.get("evidence") or retrieve(topic, k=5)
    context_parts.append("## Evidence Excerpts\n" + evidence)

    if current_round > 0:
        # Summarise prior claims for continuity
        prior_claims = [c for c in existing_claims if c.round < current_round]
        if prior_claims:
            lines = [
                f"- [{c.agent_id}] (round {c.round}, {c.confidence.value}): {c.content}"
                for c in prior_claims[-6:]  # cap to avoid context bloat
            ]
            context_parts.append("## Prior Claims\n" + "\n".join(lines))

        # Show active challenges targeting our previous claims
        my_claims = [c for c in existing_claims if c.agent_id == _agent_id]
        my_ids = {c.id for c in my_claims}
        active_challenges = [
            ch for ch in existing_challenges if ch.target_claim_id in my_ids and not ch.resolved
        ]
        if active_challenges:
            lines = [f"- [{ch.stance.value}] {ch.content}" for ch in active_challenges[-4:]]
            context_parts.append("## Challenges to Your Prior Claims\n" + "\n".join(lines))

    if arbiter_directive is not None:
        context_parts.append(
            f"## Arbiter Directive (round {arbiter_directive.round})\n"
            f"Focus areas: {', '.join(arbiter_directive.focus_dimensions)}\n"
            f"Disagreement: {arbiter_directive.disagreement_summary}\n"
            f"Instruction: {arbiter_directive.prompt}"
        )

    context_parts.append(f"## Current Round\n{current_round}")

    human_content = "\n\n".join(context_parts)

    # --- 3. LLM call with structured output ---
    structured_llm = agent_structured_llm(_agent_id, config, ResearcherOutput, temperature=0.2)

    output = t.cast(
        ResearcherOutput,
        structured_llm.invoke(
            [
                SystemMessage(content=RESEARCHER_SYSTEM_PROMPT),
                HumanMessage(content=human_content),
            ]
        ),
    )

    # Compute embedding for the claim
    claim_embedding = _get_embedder().embed_query(output.content)

    claim = Claim(
        agent_id=_agent_id,
        round=current_round,
        content=output.content,
        dimensions=output.dimensions,
        confidence=output.confidence,
        evidence_summary=output.evidence_summary,
        embedding=claim_embedding,
    )

    return {"evidence": evidence, "claims": [*existing_claims, claim]}


def researcher_node(state: ThinkTankState) -> dict:
    """Instrumented wrapper: records latency for the whole agent node."""
    with span("researcher", "node", round=state.get("current_round", 0)):
        return _researcher_node_body(state)
