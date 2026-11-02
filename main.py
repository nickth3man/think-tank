"""main.py — Run the Think Tank multi-agent deliberation system.

Reads provider credentials from the environment (e.g. ~/.zshenv), seeds the
Chroma vector store with dummy knowledge-base documents when it is empty, then
prompts for a topic and executes a full deliberation cycle using the LangGraph
pipeline.

Run setup (credential check, seeding, state defaults) lives in
:mod:`think_tank.runner` and is shared with the dashboard entry point.
"""

from __future__ import annotations

import sys
import textwrap
import time
import typing as t

from think_tank.graph import build_think_tank_graph
from think_tank.kb import SEED_DOCUMENTS
from think_tank.llm import resolve_embedding_provider, resolve_provider
from think_tank.runner import MissingCredentialsError, initial_state, prepare_run
from think_tank.state import ThinkTankState
from think_tank.telemetry import RECORDER, run_scope, span

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
            print(f"    [{ch.agent_id} -> {ch.stance.value}] target={ch.target_claim_id[:8]}...")
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
        print(f"\n  Arbiter Directive -> loop back for round {expansion.round}")
        print(f"    Focus: {', '.join(expansion.focus_dimensions)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the Think Tank multi-agent deliberation system."""
    # 1. Verify provider credentials and seed the vector store (shared setup)
    try:
        prepared = prepare_run()
    except MissingCredentialsError as exc:
        raise SystemExit(
            f"Missing credentials: {', '.join(exc.missing)}. Export them in your shell "
            f"(e.g. ~/.zshenv) or select another provider with THINK_TANK_PROVIDER."
        ) from exc

    print(
        f"[config] chat provider={resolve_provider().name} "
        f"embeddings provider={resolve_embedding_provider().name}"
    )
    if prepared.seeded:
        print(f"[seed] Populated Chroma with {len(SEED_DOCUMENTS)} dummy documents.\n")
    else:
        print("[seed] Chroma collection already has documents — skipping seed.\n")

    # 2. Build the LangGraph
    with span("startup.graph_build", "startup"):
        graph = build_think_tank_graph()

    # 3. Define the deliberation topic (CLI args or interactive prompt)
    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:]).strip()
    else:
        topic = input("Enter the topic or task for the Think Tank: ").strip()

    if not topic:
        raise SystemExit("No topic provided. Pass it as a CLI argument or enter it when prompted.")

    state = initial_state(topic)

    _print_separator(f"THINK TANK — Topic: {topic}")

    # 4. Stream the graph execution, printing state after each super-step
    seen_rounds: set[int] = set()
    run_id = f"cli_{int(time.time())}"
    with run_scope(run_id), span("graph.stream", "graph"):
        for event in graph.stream(state, stream_mode="values"):
            round_num = event.get("current_round", 0)  # type: ignore[union-attr]
            if round_num not in seen_rounds:
                seen_rounds.add(round_num)
                _print_state(t.cast(ThinkTankState, event))

    # 5. Final summary
    _print_separator("DELIBERATION COMPLETE")
    if RECORDER.enabled():
        print(RECORDER.report(run_id=run_id))


if __name__ == "__main__":
    main()
