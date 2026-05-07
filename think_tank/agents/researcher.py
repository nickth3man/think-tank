"""think_tank/agents/researcher.py — Researcher agent: grounds discussion in evidence."""

from __future__ import annotations

import typing as t

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from think_tank.schemas import Claim, ResearcherOutput
from think_tank.state import ThinkTankState

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
- `content`: A concise but substantive claim (≥ 50 words) backed by evidence.
- `dimensions`: Assess at least 3 relevant aspects, e.g. \
{"feasibility": "high", "risk": "moderate", "impact": "high", "evidence_strength": "strong"}.
- `confidence`: Rate honestly — LOW if evidence is thin, HIGH only when well-supported.
- `evidence_summary`: 1-3 sentence summary of the key evidence supporting your claim.
"""

# ---------------------------------------------------------------------------
# Node Function
# ---------------------------------------------------------------------------

_agent_id = "researcher"


def researcher_node(state: ThinkTankState) -> dict:
    """
    LangGraph node: produces an evidence-grounded Claim.

    Flow:
        1. Read topic, round, and any arbiter expansion directive.
        2. Retrieve relevant documents from the vector knowledge base.
        3. Call the LLM with structured output → ResearcherOutput.
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
            ch for ch in existing_challenges
            if ch.target_claim_id in my_ids and not ch.resolved
        ]
        if active_challenges:
            lines = [
                f"- [{ch.stance.value}] {ch.content}"
                for ch in active_challenges[-4:]
            ]
            context_parts.append("## Challenges to Your Prior Claims\n" + "\n".join(lines))

    if arbiter_directive is not None:
        context_parts.append(
            f"## Arbiter Directive (round {arbiter_directive.round})\n"
            f"Focus areas: {', '.join(arbiter_directive.focus_dimensions)}\n"
            f"Disagreement: {arbiter_directive.disagreement_summary}\n"
            f"Instruction: {arbiter_directive.prompt}"
        )

    context_parts.append(f"## Current Round\n{current_round}")

    # --- 2. Query the vector knowledge base ---
    # (In production, swap this stub for a real Chroma retriever call.)
    evidence_text = _query_knowledge_base(topic, state)

    context_parts.append(f"## Retrieved Evidence\n{evidence_text}")

    human_content = "\n\n".join(context_parts)

    # --- 3. LLM call with structured output ---
    model_name = config.get("researcher_model", "gpt-4o")
    llm = ChatOpenAI(model=model_name, temperature=0.2)
    structured_llm = llm.with_structured_output(ResearcherOutput, method="json_schema")

    output = t.cast(ResearcherOutput, structured_llm.invoke([
        SystemMessage(content=RESEARCHER_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]))

    # --- 4. Hydrate the full Claim ---
    claim = Claim(
        agent_id=_agent_id,
        round=current_round,
        content=output.content,
        dimensions=output.dimensions,
        confidence=output.confidence,
        evidence_summary=output.evidence_summary,
    )

    return {"claims": existing_claims + [claim]}


# ---------------------------------------------------------------------------
# Knowledge-base stub — replace with real Chroma retriever in production
# ---------------------------------------------------------------------------

def _query_knowledge_base(topic: str, state: ThinkTankState) -> str:
    """
    Retrieve relevant documents from the vector store.

    In production, wire this to:
        from langchain_chroma import Chroma
        from langchain_openai import OpenAIEmbeddings
        vector_store = Chroma(
            collection_name="think_tank_kb",
            embedding_function=OpenAIEmbeddings(),
        )
        results = vector_store.similarity_search(topic, k=5)
        return "\n".join(doc.page_content for doc in results)
    """
    # Stub: return the topic itself so the agent still functions in testing.
    return (
        f"[Knowledge base stub] No pre-indexed documents found for: {topic!r}. "
        "Replace this stub with a real Chroma vector-store retriever."
    )
