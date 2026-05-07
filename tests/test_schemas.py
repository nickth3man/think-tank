"""Tests for think_tank/schemas.py — Pydantic model validation."""

from __future__ import annotations

import pytest
from dirty_equals import IsStr, IsUUID
from freezegun import freeze_time
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from think_tank.schemas import (
    Challenge,
    Claim,
    Confidence,
    Expansion,
    LateralIdea,
    Stance,
    Synthesis,
    SynthesisAttempt,
)

# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


class TestClaim:
    def test_auto_uuid(self) -> None:
        c1 = Claim(agent_id="x", round=0, content="A" * 10)
        c2 = Claim(agent_id="x", round=0, content="A" * 10)
        assert c1.id != c2.id
        assert c1.id == IsStr(regex=r"[0-9a-f-]{36}")

    def test_content_min_length(self) -> None:
        with pytest.raises(ValidationError, match="string_too_short"):
            Claim(agent_id="x", round=0, content="short")

    def test_agent_id_min_length(self) -> None:
        with pytest.raises(ValidationError):
            Claim(agent_id="", round=0, content="A valid content string here")

    def test_round_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            Claim(agent_id="x", round=-1, content="A valid content string here")

    def test_default_confidence_is_medium(self) -> None:
        claim = Claim(agent_id="x", round=0, content="A" * 10)
        assert claim.confidence == Confidence.MEDIUM

    def test_explicit_confidence(self) -> None:
        claim = Claim(agent_id="x", round=0, content="A" * 10, confidence=Confidence.HIGH)
        assert claim.confidence == Confidence.HIGH

    def test_embedding_default_empty(self) -> None:
        claim = Claim(agent_id="x", round=0, content="A" * 10)
        assert claim.embedding == []

    def test_dimensions_default_empty(self) -> None:
        claim = Claim(agent_id="x", round=0, content="A" * 10)
        assert claim.dimensions == {}

    @freeze_time("2025-01-15T12:00:00Z")
    def test_created_at_set_on_construction(self) -> None:
        claim = Claim(agent_id="x", round=0, content="A" * 10)
        assert claim.created_at.year == 2025
        assert claim.created_at.month == 1

    @given(
        content=st.text(min_size=10, max_size=500).filter(lambda s: s.strip()),
        round_num=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=50)
    def test_hypothesis_valid_claims(self, content: str, round_num: int) -> None:
        claim = Claim(agent_id="agent", round=round_num, content=content)
        assert claim.round == round_num
        assert claim.content == content

    def test_roundtrip_json(self) -> None:
        original = Claim(
            agent_id="researcher",
            round=1,
            content="A well-grounded evidence-based claim here.",
            dimensions={"feasibility": "high"},
            confidence=Confidence.HIGH,
        )
        restored = Claim.model_validate_json(original.model_dump_json())
        assert restored.id == original.id
        assert restored.content == original.content
        assert restored.confidence == original.confidence


# ---------------------------------------------------------------------------
# Challenge
# ---------------------------------------------------------------------------


class TestChallenge:
    def test_requires_valid_target_claim_id(self) -> None:
        with pytest.raises(ValidationError):
            Challenge(
                agent_id="skeptic",
                target_claim_id="",
                round=1,
                stance=Stance.OPPOSE,
                content="A" * 10,
            )

    def test_content_min_length(self) -> None:
        with pytest.raises(ValidationError):
            Challenge(
                agent_id="skeptic",
                target_claim_id="some-id",
                round=1,
                stance=Stance.OPPOSE,
                content="short",
            )

    def test_default_not_resolved(self) -> None:
        challenge = Challenge(
            agent_id="skeptic",
            target_claim_id="abc-123",
            round=1,
            stance=Stance.OPPOSE,
            content="This argument has a significant logical gap in reasoning.",
        )
        assert challenge.resolved is False

    @pytest.mark.parametrize("stance", list(Stance))
    def test_all_stances_valid(self, stance: Stance) -> None:
        challenge = Challenge(
            agent_id="skeptic",
            target_claim_id="abc-123",
            round=1,
            stance=stance,
            content="A substantive challenge to the stated position here.",
        )
        assert challenge.stance == stance


# ---------------------------------------------------------------------------
# LateralIdea
# ---------------------------------------------------------------------------


class TestLateralIdea:
    def test_content_and_rationale_required(self) -> None:
        with pytest.raises(ValidationError):
            LateralIdea(
                agent_id="visionary",
                round=1,
                content="A" * 10,
                # missing novelty_rationale
            )

    def test_valid_construction(self) -> None:
        idea = LateralIdea(
            agent_id="visionary",
            round=1,
            content="What if we inverted the incentive structure entirely?",
            novelty_rationale="Applies game theory inversion not yet explored.",
        )
        assert idea.related_claim_ids == []
        assert idea.agent_id == "visionary"


# ---------------------------------------------------------------------------
# SynthesisAttempt
# ---------------------------------------------------------------------------


class TestSynthesisAttempt:
    def test_valid_construction(self) -> None:
        attempt = SynthesisAttempt(
            agent_id="synthesizer",
            round=2,
            content="Both claims can be reconciled through a contextual framework.",
        )
        assert attempt.resolved_tensions == []
        assert attempt.remaining_tensions == []
        assert attempt.confidence == Confidence.MEDIUM


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


class TestExpansion:
    def test_focus_dimensions_required_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            Expansion(
                round=2,
                focus_dimensions=[],
                prompt="A" * 10,
                disagreement_summary="Some disagreement.",
            )

    def test_valid_construction(self) -> None:
        exp = Expansion(
            round=2,
            focus_dimensions=["feasibility", "risk"],
            prompt="Please elaborate on feasibility concerns from agents.",
            disagreement_summary="Agents disagree on feasibility and risk assessment.",
        )
        assert exp.round == 2
        assert "feasibility" in exp.focus_dimensions


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


class TestSynthesis:
    def test_alignment_score_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Synthesis(
                content="Final answer.",
                contributing_claim_ids=["id1"],
                alignment_score=1.5,  # out of bounds
                rounds_taken=2,
            )

    def test_rounds_taken_minimum_one(self) -> None:
        with pytest.raises(ValidationError):
            Synthesis(
                content="Final answer.",
                contributing_claim_ids=["id1"],
                alignment_score=0.8,
                rounds_taken=0,
            )

    def test_valid_synthesis(self) -> None:
        s = Synthesis(
            content="The group converged on a unified position after deliberation.",
            contributing_claim_ids=["id1", "id2"],
            alignment_score=0.82,
            rounds_taken=3,
        )
        assert s.id == IsUUID
        assert s.alignment_score == pytest.approx(0.82)


# ---------------------------------------------------------------------------
# Confidence & Stance enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_confidence_values(self) -> None:
        assert set(Confidence) == {Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH}

    def test_stance_values(self) -> None:
        assert set(Stance) == {Stance.SUPPORT, Stance.OPPOSE, Stance.REFINE}

    def test_str_enum_equality(self) -> None:
        assert Confidence.LOW == "low"
        assert Stance.OPPOSE == "oppose"
