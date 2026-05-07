"""Tests for think_tank/arbiter.py — pure alignment logic (no LLM calls)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.conftest import make_challenge, make_claim
from think_tank.arbiter import (
    _challenge_resolution_rate,
    _cosine_similarity,
    _find_weak_dimensions,
    _opposition_ratio,
    _pairwise_alignment,
    arbiter_node,
    route_after_arbiter,
)
from think_tank.schemas import Claim, Stance, Synthesis
from think_tank.state import ThinkTankState

# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors_return_one(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_return_zero(self) -> None:
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_return_minus_one(self) -> None:
        assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_empty_vectors_return_zero(self) -> None:
        assert _cosine_similarity([], []) == 0.0

    def test_zero_norm_vector_returns_zero(self) -> None:
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_mismatched_lengths_return_zero(self) -> None:
        assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    @given(st.lists(st.floats(min_value=-10, max_value=10), min_size=1, max_size=8))
    @settings(max_examples=100)
    def test_result_in_range(self, v: list[float]) -> None:
        if all(x == 0.0 for x in v):
            return
        result = _cosine_similarity(v, v)
        assert -1.0 - 1e-6 <= result <= 1.0 + 1e-6


# ---------------------------------------------------------------------------
# _pairwise_alignment
# ---------------------------------------------------------------------------


class TestPairwiseAlignment:
    def test_single_claim_returns_one(self, aligned_claims: list[Claim]) -> None:
        assert _pairwise_alignment([aligned_claims[0]]) == pytest.approx(1.0)

    def test_aligned_claims_return_one(self, aligned_claims: list[Claim]) -> None:
        score = _pairwise_alignment(aligned_claims)
        assert score == pytest.approx(1.0, abs=1e-4)

    def test_orthogonal_claims_return_zero(self, diverged_claims: list[Claim]) -> None:
        score = _pairwise_alignment(diverged_claims)
        assert score == pytest.approx(0.0, abs=1e-4)

    def test_empty_list_returns_one(self) -> None:
        assert _pairwise_alignment([]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _challenge_resolution_rate
# ---------------------------------------------------------------------------


class TestChallengeResolutionRate:
    def test_no_challenges_returns_one(self) -> None:
        assert _challenge_resolution_rate([]) == pytest.approx(1.0)

    def test_all_resolved(self) -> None:
        challenges = [make_challenge(resolved=True) for _ in range(3)]
        assert _challenge_resolution_rate(challenges) == pytest.approx(1.0)

    def test_none_resolved(self) -> None:
        challenges = [make_challenge(resolved=False) for _ in range(4)]
        assert _challenge_resolution_rate(challenges) == pytest.approx(0.0)

    def test_half_resolved(self) -> None:
        challenges = [
            make_challenge(resolved=True),
            make_challenge(resolved=True),
            make_challenge(resolved=False),
            make_challenge(resolved=False),
        ]
        assert _challenge_resolution_rate(challenges) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _opposition_ratio
# ---------------------------------------------------------------------------


class TestOppositionRatio:
    def test_no_challenges_returns_zero(self) -> None:
        assert _opposition_ratio([]) == pytest.approx(0.0)

    def test_all_oppose(self) -> None:
        challenges = [make_challenge(stance=Stance.OPPOSE) for _ in range(3)]
        assert _opposition_ratio(challenges) == pytest.approx(1.0)

    def test_no_oppose(self) -> None:
        challenges = [
            make_challenge(stance=Stance.SUPPORT),
            make_challenge(stance=Stance.REFINE),
        ]
        assert _opposition_ratio(challenges) == pytest.approx(0.0)

    def test_mixed_stances(self) -> None:
        challenges = [
            make_challenge(stance=Stance.OPPOSE),
            make_challenge(stance=Stance.SUPPORT),
            make_challenge(stance=Stance.REFINE),
            make_challenge(stance=Stance.OPPOSE),
        ]
        assert _opposition_ratio(challenges) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _find_weak_dimensions
# ---------------------------------------------------------------------------


class TestFindWeakDimensions:
    def test_empty_claims_returns_empty(self) -> None:
        assert _find_weak_dimensions([]) == []

    def test_no_disagreement_returns_empty(self) -> None:
        claims = [
            make_claim(dimensions={"feasibility": "high"}),
            make_claim(dimensions={"feasibility": "high"}),
        ]
        assert _find_weak_dimensions(claims) == []

    def test_disagreement_on_dimension_detected(self) -> None:
        claims = [
            make_claim(dimensions={"feasibility": "high", "risk": "low"}),
            make_claim(dimensions={"feasibility": "low", "risk": "low"}),
        ]
        weak = _find_weak_dimensions(claims)
        assert "feasibility" in weak

    def test_returns_at_most_three(self) -> None:
        claims = [
            make_claim(dimensions={"a": "x", "b": "x", "c": "x", "d": "x"}),
            make_claim(dimensions={"a": "y", "b": "y", "c": "y", "d": "y"}),
        ]
        assert len(_find_weak_dimensions(claims)) <= 3


# ---------------------------------------------------------------------------
# arbiter_node — integration (no LLM, pure computation)
# ---------------------------------------------------------------------------


class TestArbiterNode:
    def _make_state(
        self,
        claims: list | None = None,
        challenges: list | None = None,
        current_round: int = 2,
        config: dict | None = None,
    ) -> ThinkTankState:
        return {
            "topic": "Should remote work be the default?",
            "claims": claims or [],
            "challenges": challenges or [],
            "current_round": current_round,
            "config": config or {"alignment_threshold": 0.75, "min_rounds": 2, "max_rounds": 6},
            "syntheses": [],
            "expansions": [],
            "synthesis": None,
            "expansion": None,
            "alignment_score": 0.0,
        }

    def test_converges_when_aligned_and_min_rounds_met(self, aligned_claims: list[Claim]) -> None:
        # aligned_claims have round=1; use round=2 claims to match current_round=2
        claims = [
            make_claim(agent_id=c.agent_id, round=2, embedding=c.embedding) for c in aligned_claims
        ]
        state = self._make_state(claims=claims, current_round=2)
        result = arbiter_node(state)
        assert isinstance(result["synthesis"], Synthesis)
        assert result["expansion"] is None

    def test_expands_when_diverged(self, diverged_claims: list[Claim]) -> None:
        # diverged_claims have round=1; current_round must match so arbiter finds them
        state = self._make_state(claims=diverged_claims, current_round=1)
        result = arbiter_node(state)
        assert result["synthesis"] is None
        assert result["expansion"] is not None

    def test_forced_convergence_at_max_rounds(self, diverged_claims: list[Claim]) -> None:
        # Use claims at round=6 to match current_round
        claims = [
            make_claim(agent_id=c.agent_id, round=6, embedding=c.embedding) for c in diverged_claims
        ]
        state = self._make_state(claims=claims, current_round=6)
        result = arbiter_node(state)
        assert isinstance(result["synthesis"], Synthesis)

    def test_expands_below_min_rounds_even_if_aligned(self, aligned_claims: list[Claim]) -> None:
        # aligned_claims have round=1; current_round=1 matches
        state = self._make_state(
            claims=aligned_claims,
            current_round=1,
            config={"alignment_threshold": 0.75, "min_rounds": 2, "max_rounds": 6},
        )
        result = arbiter_node(state)
        assert result["expansion"] is not None

    def test_alignment_score_clamped_between_0_and_1(self, aligned_claims: list[Claim]) -> None:
        # Use round=3 claims to match current_round=3
        claims = [
            make_claim(agent_id=c.agent_id, round=3, embedding=c.embedding) for c in aligned_claims
        ]
        state = self._make_state(claims=claims, current_round=3)
        result = arbiter_node(state)
        assert 0.0 <= result["alignment_score"] <= 1.0

    def test_increments_round(self, aligned_claims: list[Claim]) -> None:
        # Use round=2 claims to match current_round=2
        claims = [
            make_claim(agent_id=c.agent_id, round=2, embedding=c.embedding) for c in aligned_claims
        ]
        state = self._make_state(claims=claims, current_round=2)
        result = arbiter_node(state)
        assert result["current_round"] == 3


# ---------------------------------------------------------------------------
# route_after_arbiter
# ---------------------------------------------------------------------------


    def test_routes_to_end_when_synthesis_present(self) -> None:
        synthesis = Synthesis(
            content="Final merged position on the topic.",
            contributing_claim_ids=["id1"],
            alignment_score=0.85,
            rounds_taken=3,
        )
        state: ThinkTankState = {
            "topic": "test",
            "config": {},
            "claims": [],
            "challenges": [],
            "expansions": [],
            "syntheses": [],
            "current_round": 0,
            "alignment_score": 0.0,
            "expansion": None,
            "synthesis": synthesis,
        }
        assert route_after_arbiter(state) == "__end__"

    def test_routes_to_researcher_when_no_synthesis(self) -> None:
        state: ThinkTankState = {
            "topic": "test",
            "config": {},
            "claims": [],
            "challenges": [],
            "expansions": [],
            "syntheses": [],
            "current_round": 0,
            "alignment_score": 0.0,
            "expansion": None,
            "synthesis": None,
        }
        assert route_after_arbiter(state) == "researcher"
