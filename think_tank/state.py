"""think_tank/state.py — LangGraph graph state definition."""

from __future__ import annotations

from typing import TypedDict

from think_tank.schemas import (
    Challenge,
    Claim,
    Expansion,
    LateralIdea,
    Synthesis,
    SynthesisAttempt,
)


class ThinkTankState(TypedDict):
    """Full state threaded through the Think Tank LangGraph."""

    # --- Input ---
    topic: str                          # The question / problem to deliberate
    config: dict                        # Runtime config (thresholds, model names, etc.)

    # --- Deliberation artifacts (accumulate across rounds) ---
    claims: list[Claim]
    challenges: list[Challenge]
    expansions: list[LateralIdea]       # Visionary's lateral ideas per round
    syntheses: list[SynthesisAttempt]   # Synthesizer's per-round merge attempts

    # --- Arbiter outputs (written each round) ---
    current_round: int
    alignment_score: float              # 0.0 – 1.0
    expansion: Expansion | None         # Set when routing back to agents (arbiter directive)
    synthesis: Synthesis | None         # Set when routing to END (final output)
