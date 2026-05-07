"""Shared pytest fixtures for the think-tank test suite."""

from __future__ import annotations

import pytest

from think_tank.schemas import Challenge, Claim, Confidence, Stance


def make_claim(
    agent_id: str = "researcher",
    round: int = 1,
    content: str = "Remote work increases productivity for knowledge workers.",
    embedding: list[float] | None = None,
    confidence: Confidence = Confidence.MEDIUM,
    dimensions: dict[str, str] | None = None,
    **kwargs,
) -> Claim:
    return Claim(
        agent_id=agent_id,
        round=round,
        content=content,
        embedding=embedding or [],
        confidence=confidence,
        dimensions=dimensions or {},
        **kwargs,
    )


def make_challenge(
    target_claim: Claim | None = None,
    agent_id: str = "skeptic",
    round: int = 1,
    stance: Stance = Stance.OPPOSE,
    content: str = "This claim lacks empirical grounding from controlled studies.",
    resolved: bool = False,
    **kwargs,
) -> Challenge:
    claim = target_claim or make_claim()
    return Challenge(
        agent_id=agent_id,
        target_claim_id=claim.id,
        round=round,
        stance=stance,
        content=content,
        resolved=resolved,
        **kwargs,
    )


@pytest.fixture
def sample_claim() -> Claim:
    return make_claim()


@pytest.fixture
def sample_challenge(sample_claim: Claim) -> Challenge:
    return make_challenge(target_claim=sample_claim)


@pytest.fixture
def aligned_claims() -> list[Claim]:
    """Three claims with identical embeddings — maximally aligned."""
    vec = [1.0, 0.0, 0.0]
    return [make_claim(agent_id=f"agent_{i}", round=1, embedding=vec) for i in range(3)]


@pytest.fixture
def diverged_claims() -> list[Claim]:
    """Three claims with orthogonal embeddings — maximally diverged."""
    return [
        make_claim(agent_id="researcher", round=1, embedding=[1.0, 0.0, 0.0]),
        make_claim(agent_id="skeptic", round=1, embedding=[0.0, 1.0, 0.0]),
        make_claim(agent_id="visionary", round=1, embedding=[0.0, 0.0, 1.0]),
    ]
