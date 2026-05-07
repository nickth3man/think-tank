"""think_tank/arbiter.py — Arbiter node + routing function."""

from __future__ import annotations

import math
from typing import Literal

from think_tank.schemas import (
    Challenge,
    Claim,
    Expansion,
    Stance,
    Synthesis,
)
from think_tank.state import ThinkTankState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _pairwise_alignment(claims: list[Claim]) -> float:
    """Mean pairwise cosine similarity across all agent claims in the latest round."""
    if len(claims) < 2:
        return 1.0  # single agent -> trivially aligned

    scores: list[float] = [
        _cosine_similarity(claims[i].embedding, claims[j].embedding)
        for i in range(len(claims))
        for j in range(i + 1, len(claims))
    ]
    return sum(scores) / len(scores)


def _challenge_resolution_rate(challenges: list[Challenge]) -> float:
    """Fraction of challenges that have been resolved (accepted)."""
    if not challenges:
        return 1.0
    resolved = sum(1 for c in challenges if c.resolved)
    return resolved / len(challenges)


def _opposition_ratio(challenges: list[Challenge]) -> float:
    """Fraction of challenges that are OPPOSE stance — lower is better for convergence."""
    if not challenges:
        return 0.0
    opposed = sum(1 for c in challenges if c.stance == Stance.OPPOSE)
    return opposed / len(challenges)


def _find_weak_dimensions(claims: list[Claim]) -> list[str]:
    """Return dimensions where agents disagree most (heuristic: most unique values)."""
    if not claims:
        return []
    # Dimensions with the most distinct values = most disagreement
    distinct: dict[str, set[str]] = {}
    for claim in claims:
        for dim, value in claim.dimensions.items():
            distinct.setdefault(dim, set()).add(value)
    # Sort by number of distinct values descending -> most disagreement first
    ranked = sorted(distinct.items(), key=lambda kv: len(kv[1]), reverse=True)
    return [dim for dim, vals in ranked if len(vals) > 1][:3]  # top 3 weak spots


# ---------------------------------------------------------------------------
# Arbiter Node
# ---------------------------------------------------------------------------

ALIGNMENT_THRESHOLD = 0.75  # minimum alignment to declare convergence
MIN_ROUNDS = 2  # force at least this many rounds
MAX_ROUNDS = 6  # hard ceiling — converge or produce best-effort


def arbiter_node(state: ThinkTankState) -> dict:
    """
    Evaluates agent alignment and produces either:
      - an Expansion (route back to agents), or
      - a Synthesis  (route to END).

    Returns a partial state update dict (LangGraph convention).
    """
    claims = state.get("claims", [])
    challenges = state.get("challenges", [])
    current_round = state.get("current_round", 0)
    topic = state["topic"]

    config = state.get("config", {})
    threshold = config.get("alignment_threshold", ALIGNMENT_THRESHOLD)
    min_rounds = config.get("min_rounds", MIN_ROUNDS)
    max_rounds = config.get("max_rounds", MAX_ROUNDS)

    # --- Filter claims to the CURRENT round only ---
    latest_claims = [c for c in claims if c.round == current_round]
    latest_challenges = [c for c in challenges if c.round == current_round]

    # --- Compute alignment components ---
    semantic_alignment = _pairwise_alignment(latest_claims)
    resolution_rate = _challenge_resolution_rate(latest_challenges)
    opposition = _opposition_ratio(latest_challenges)

    # Weighted composite: semantic similarity is primary, penalize unresolved opposition
    alignment_score = 0.60 * semantic_alignment + 0.25 * resolution_rate + 0.15 * (1.0 - opposition)
    alignment_score = round(min(max(alignment_score, 0.0), 1.0), 4)

    # --- Convergence decision ---
    converged = alignment_score >= threshold and current_round >= min_rounds
    forced_end = current_round >= max_rounds

    if converged or forced_end:
        # === PRODUCE SYNTHESIS -> route to END ===
        verdict = "forced" if forced_end and not converged else "natural"
        synthesis_content = _build_synthesis_content(topic, latest_claims, challenges, verdict)
        synthesis = Synthesis(
            content=synthesis_content,
            contributing_claim_ids=[c.id for c in latest_claims],
            alignment_score=alignment_score,
            rounds_taken=current_round + 1,
            unresolved_challenges=[c.id for c in challenges if not c.resolved],
        )
        return {
            "alignment_score": alignment_score,
            "synthesis": synthesis,
            "expansion": None,
            "current_round": current_round + 1,
        }

    # === PRODUCE EXPANSION -> route back to researcher ===
    weak_dims = _find_weak_dimensions(latest_claims)
    if not weak_dims:
        weak_dims = ["overall reasoning"]

    expansion = Expansion(
        round=current_round + 1,
        focus_dimensions=weak_dims,
        prompt=(
            f"The group has not yet aligned on: {', '.join(weak_dims)}. "
            f"Current alignment is {alignment_score:.2f} (target: {threshold}). "
            f"Please refine your position, addressing the strongest objections "
            f"from other agents."
        ),
        disagreement_summary=_summarize_disagreement(latest_claims, challenges),
    )
    return {
        "alignment_score": alignment_score,
        "expansion": expansion,
        "synthesis": None,
        "current_round": current_round + 1,
    }


# ---------------------------------------------------------------------------
# Helpers for synthesis generation
# ---------------------------------------------------------------------------


def _build_synthesis_content(
    topic: str,
    claims: list[Claim],
    challenges: list[Challenge],
    verdict: str,
) -> str:
    """Merge agent positions into a unified answer string.

    In production, this would call an LLM. Here we provide a deterministic fallback.
    """
    prefix = (
        "Convergence reached. "
        if verdict == "natural"
        else "Max rounds reached — best-effort synthesis. "
    )
    positions = "\n".join(
        f"- Agent {c.agent_id} ({c.confidence.value} confidence): {c.content}" for c in claims
    )
    return f"{prefix}Topic: {topic}\n\nPositions:\n{positions}"


def _summarize_disagreement(claims: list[Claim], challenges: list[Challenge]) -> str:
    """Brief human-readable summary of where agents diverge."""
    if not challenges:
        return "No explicit challenges raised yet — agents may be implicitly misaligned."
    active = [c for c in challenges if not c.resolved]
    if not active:
        return "All challenges resolved — alignment should be high."
    lines = [
        f"{c.agent_id} -> claim {c.target_claim_id[:8]}... ({c.stance.value}): {c.content[:120]}"
        for c in active[:5]
    ]
    return "Unresolved challenges:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Routing Function — wired via graph.add_conditional_edges("arbiter", route_after_arbiter, ...)
# ---------------------------------------------------------------------------


def route_after_arbiter(
    state: ThinkTankState,
) -> Literal["researcher", "__end__"]:
    """
    Called by LangGraph after the arbiter node runs.
    Returns the name of the next node (or END).
    """
    if state.get("synthesis") is not None:
        return "__end__"
    return "researcher"
