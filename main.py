"""main.py — Run the Think Tank multi-agent deliberation system.

Loads environment variables (python-dotenv), seeds the Chroma vector store
with dummy knowledge-base documents when it is empty, then executes a full
deliberation cycle on a sample topic using the LangGraph pipeline.
"""

from __future__ import annotations

import os
import textwrap
import typing as t

from dotenv import load_dotenv


from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from think_tank.graph import build_think_tank_graph
from think_tank.state import ThinkTankState


# ---------------------------------------------------------------------------
# Dummy documents used to seed an empty Chroma collection
# ---------------------------------------------------------------------------

_SEED_DOCUMENTS = [
    "Remote work has been shown to increase productivity for knowledge workers "
    "by 13% according to a Stanford study conducted over 9 months with 16,000 "
    "employees. The increase was attributed to quieter work environments and "
    "fewer sick days.",

    "A 2023 McKinsey report found that 87% of workers offered flexible work "
    "arrangements choose to work remotely at least part of the time. Employee "
    "satisfaction scores rose by 20% when remote options were available.",

    "Communication overhead increases by approximately 30% in fully remote "
    "teams due to reliance on asynchronous channels, according to a Microsoft "
    "study of 60,000 employees. This can lead to slower decision-making in "
    "time-sensitive situations.",

    "Hybrid work models (2-3 days in-office) appear to balance productivity "
    "gains with team cohesion. A Harvard Business Review meta-analysis of 45 "
    "studies found hybrid arrangements produced optimal outcomes for both "
    "employee well-being and business metrics.",

    "Remote work exacerbates the 'always-on' culture: 62% of remote workers "
    "report difficulty disconnecting after work hours (Buffer State of Remote "
    "Work 2023). This can lead to burnout despite apparent schedule flexibility.",

    "Innovation metrics decline in fully remote settings according to a Nature "
    "Human Behaviour study analysing 20 million research papers. Face-to-face "
    "interactions were found to be significantly more likely to produce "
    "novel, breakthrough ideas compared to virtual collaboration.",

    "Cost savings from remote work are substantial: companies save an average "
    "of $11,000 per remote employee per year on real estate, utilities, and "
    "office supplies (Global Workplace Analytics 2023 estimate).",

    "Onboarding new employees remotely takes 32% longer on average compared "
    "to in-person onboarding, according to a 2022 Gartner survey of 500 HR "
    "leaders. Knowledge transfer and culture assimilation were cited as the "
    "primary challenges.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_vector_store() -> Chroma:
    """Return a Chroma vector store using the configured DB path."""
    db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    return Chroma(
        collection_name="think_tank_kb",
        embedding_function=OpenAIEmbeddings(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model=os.getenv("OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
            check_embedding_ctx_length=False
        ),
        persist_directory=db_path,
    )


def _seed_if_empty(vector_store: Chroma) -> None:
    """Populate the vector store with dummy documents when the collection is empty."""
    existing = vector_store.similarity_search("remote work productivity", k=1)
    if existing:
        print("[seed] Chroma collection already has documents — skipping seed.\n")
        return

    print(f"[seed] Populating Chroma with {len(_SEED_DOCUMENTS)} dummy documents …")
    from langchain_core.documents import Document

    documents = [
        Document(page_content=text, metadata={"source": "seed", "index": i})
        for i, text in enumerate(_SEED_DOCUMENTS)
    ]
    vector_store.add_documents(documents)
    print("[seed] Done.\n")


def _print_separator(title: str) -> None:
    """Print a visible section separator."""
    width = 72
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def _print_state(state: ThinkTankState) -> None:
    """Pretty-print the current ThinkTankState after a deliberation round."""
    current_round = state.get("current_round", 0)
    alignment = state.get("alignment_score", 0.0)

    print(f"\n  Round ............. {current_round}")
    print(f"  Alignment score ... {alignment:.4f}")

    # Claims
    claims = state.get("claims", [])
    if claims:
        print(f"\n  Claims ({len(claims)}):")
        for c in claims:
            print(f"    [{c.agent_id}] round={c.round} confidence={c.confidence.value}")
            print(f"      {textwrap.shorten(c.content, width=120)}")

    # Challenges
    challenges = state.get("challenges", [])
    if challenges:
        print(f"\n  Challenges ({len(challenges)}):")
        for ch in challenges:
            print(f"    [{ch.agent_id} → {ch.stance.value}] target={ch.target_claim_id[:8]}…")
            print(f"      {textwrap.shorten(ch.content, width=120)}")

    # Lateral ideas
    expansions = state.get("expansions", [])
    if expansions:
        print(f"\n  Lateral Ideas ({len(expansions)}):")
        for e in expansions:
            print(f"    [{e.agent_id}] round={e.round}")
            print(f"      {textwrap.shorten(e.content, width=120)}")

    # Synthesis attempts
    syntheses = state.get("syntheses", [])
    if syntheses:
        print(f"\n  Synthesis Attempts ({len(syntheses)}):")
        for s in syntheses:
            print(f"    round={s.round} confidence={s.confidence.value}")
            print(f"      {textwrap.shorten(s.content, width=120)}")

    # Final synthesis
    synthesis = state.get("synthesis")
    if synthesis is not None:
        _print_separator("FINAL SYNTHESIS")
        print(f"  Rounds taken ...... {synthesis.rounds_taken}")
        print(f"  Alignment ......... {synthesis.alignment_score:.4f}")
        print(f"\n  {textwrap.fill(synthesis.content, width=72)}")
        if synthesis.unresolved_challenges:
            print(f"\n  Unresolved challenges: {len(synthesis.unresolved_challenges)}")

    # Expansion directive (if looping)
    expansion = state.get("expansion")
    if expansion is not None:
        print(f"\n  Arbiter Directive → loop back for round {expansion.round}")
        print(f"    Focus: {', '.join(expansion.focus_dimensions)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the Think Tank multi-agent deliberation system."""
    # 1. Load .env (OPENAI_API_KEY, OPENROUTER_API_KEY, CHROMA_DB_PATH, etc.)
    load_dotenv()


    if not os.getenv("OPENROUTER_API_KEY"):
        raise SystemExit(
            "OPENROUTER_API_KEY is not set. "
            "Create a .env file or export the variable before running."
        )

    vector_store = _get_vector_store()
    _seed_if_empty(vector_store)

    # 3. Build the LangGraph
    graph = build_think_tank_graph()

    # 4. Define the deliberation topic and initial state
    topic = "The impact of remote work on productivity"
    initial_state: ThinkTankState = {
        "topic": topic,
        "config": {
            "alignment_threshold": 0.65,
            "min_rounds": 2,
            "max_rounds": 6,
        },
        "claims": [],
        "challenges": [],
        "expansions": [],
        "syntheses": [],
        "current_round": 0,
        "alignment_score": 0.0,
        "expansion": None,
        "synthesis": None,
    }

    _print_separator(f"THINK TANK — Topic: {topic}")

    # 5. Stream the graph execution, printing state after each super-step
    seen_rounds: set[int] = set()
    for event in graph.stream(initial_state, stream_mode="values"):
        round_num = event.get("current_round", 0)  # type: ignore[union-attr]
        if round_num not in seen_rounds:
            seen_rounds.add(round_num)
            _print_state(t.cast(ThinkTankState, event))

    # 6. Final summary
    _print_separator("DELIBERATION COMPLETE")


if __name__ == "__main__":
    main()
