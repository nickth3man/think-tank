"""think_tank/schemas.py — Shared state models for the Think Tank multi-agent system."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Confidence(StrEnum):
    """Agent's self-reported confidence in a claim."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Stance(StrEnum):
    """Whether a challenge supports, opposes, or refines a claim."""
    SUPPORT = "support"
    OPPOSE = "oppose"
    REFINE = "refine"


class ConvergenceVerdict(StrEnum):
    """Arbiter's final routing decision."""
    CONVERGED = "converged"
    DIVERGED = "diverged"


# ---------------------------------------------------------------------------
# Core Domain Models
# ---------------------------------------------------------------------------

class Claim(BaseModel):
    """An assertion or position put forward by an agent."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique claim identifier.",
    )
    agent_id: str = Field(
        ..., min_length=1, description="ID of the originating agent."
    )
    round: int = Field(
        ..., ge=0, description="Deliberation round this claim was made in."
    )
    content: str = Field(
        ..., min_length=10, description="The claim text / agent's position."
    )
    dimensions: dict[str, str] = Field(
        default_factory=dict,
        description="Structured aspects: e.g. {'feasibility': 'high', 'risk': 'moderate'}.",
    )
    confidence: Confidence = Field(
        default=Confidence.MEDIUM, description="Agent's self-assessed confidence."
    )
    evidence_summary: str = Field(
        default="",
        description="Summary of supporting evidence (populated by Researcher).",
    )
    embedding: list[float] = Field(
        default_factory=list,
        description="Vector embedding of `content` for similarity computation.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class Challenge(BaseModel):
    """A counter-argument, support, or refinement targeting a specific claim."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique challenge identifier.",
    )
    agent_id: str = Field(
        ..., min_length=1, description="ID of the challenging agent."
    )
    target_claim_id: str = Field(
        ..., min_length=1, description="ID of the Claim being challenged."
    )
    round: int = Field(
        ..., ge=0, description="Round this challenge was made in."
    )
    stance: Stance = Field(
        ..., description="Whether the challenge supports, opposes, or refines."
    )
    content: str = Field(
        ..., min_length=10, description="The challenge / counter-argument text."
    )
    reasoning: str = Field(
        default="",
        description="Logical reasoning or counter-evidence for this challenge.",
    )
    resolved: bool = Field(
        default=False,
        description="Whether the original claim's author accepted this challenge.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class LateralIdea(BaseModel):
    """An unconventional idea or perspective expansion proposed by the Visionary."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique lateral idea identifier.",
    )
    agent_id: str = Field(
        ..., min_length=1, description="ID of the originating agent."
    )
    round: int = Field(
        ..., ge=0, description="Round this idea was proposed in.",
    )
    content: str = Field(
        ..., min_length=10,
        description="The lateral idea / expansion — unconventional yet plausible.",
    )
    related_claim_ids: list[str] = Field(
        default_factory=list,
        description="IDs of claims this idea expands upon or responds to.",
    )
    novelty_rationale: str = Field(
        ..., min_length=10,
        description="Why this idea is novel, non-obvious, yet actionable.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class SynthesisAttempt(BaseModel):
    """A per-round attempt to merge perspectives and resolve contradictions."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique synthesis attempt identifier.",
    )
    agent_id: str = Field(
        ..., min_length=1, description="ID of the synthesizing agent."
    )
    round: int = Field(
        ..., ge=0, description="Round this synthesis was produced in.",
    )
    content: str = Field(
        ..., min_length=10,
        description="The merged perspective resolving contradictions.",
    )
    incorporated_claim_ids: list[str] = Field(
        default_factory=list,
        description="IDs of claims incorporated into this synthesis.",
    )
    resolved_tensions: list[str] = Field(
        default_factory=list,
        description="Contradictions or disagreements that were resolved.",
    )
    remaining_tensions: list[str] = Field(
        default_factory=list,
        description="Contradictions that remain unresolved.",
    )
    confidence: Confidence = Field(
        default=Confidence.MEDIUM,
        description="Confidence in the quality of this synthesis.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class Expansion(BaseModel):
    """Directive from the Arbiter requesting agents to elaborate on weak spots."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique expansion identifier.",
    )
    round: int = Field(
        ..., ge=0, description="The upcoming round agents should expand into.",
    )
    focus_dimensions: list[str] = Field(
        ..., min_length=1,
        description="Dimensions with lowest agreement that need elaboration.",
    )
    prompt: str = Field(
        ..., min_length=10,
        description="Specific instructions to agents for the next round.",
    )
    disagreement_summary: str = Field(
        ..., description="What agents currently disagree on and why.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class Synthesis(BaseModel):
    """The converged, merged output when agents reach alignment."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique synthesis identifier.",
    )
    content: str = Field(
        ..., min_length=10, description="Final merged position / answer."
    )
    contributing_claim_ids: list[str] = Field(
        ..., description="IDs of all claims that contributed to the synthesis."
    )
    alignment_score: float = Field(
        ..., ge=0.0, le=1.0, description="Final alignment score at convergence.",
    )
    rounds_taken: int = Field(
        ..., ge=1, description="Number of deliberation rounds to reach convergence.",
    )
    unresolved_challenges: list[str] = Field(
        default_factory=list,
        description="IDs of challenges still open at convergence time.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )



# ---------------------------------------------------------------------------
# LLM Output Models - used with with_structured_output()
# These exclude auto-generated / metadata fields; the node functions
# hydrate the full domain models after LLM invocation.
# ---------------------------------------------------------------------------

class ResearcherOutput(BaseModel):
    """Structured output from the Researcher LLM call."""

    content: str = Field(
        ..., min_length=10,
        description="Evidence-grounded claim text.",
    )
    dimensions: dict[str, str] = Field(
        default_factory=dict,
        description="Structured assessment (e.g. feasibility, risk, impact).",
    )
    confidence: Confidence = Field(
        default=Confidence.MEDIUM,
    )
    evidence_summary: str = Field(
        ..., min_length=5,
        description="Concise summary of evidence supporting this claim.",
    )


class SkepticOutput(BaseModel):
    """Structured output from the Skeptic LLM call."""

    target_claim_id: str = Field(
        ..., min_length=1,
        description="ID of the claim being challenged.",
    )
    stance: Stance = Field(
        ..., description="Support, oppose, or refine.",
    )
    content: str = Field(
        ..., min_length=10,
        description="The challenge / counter-argument text.",
    )
    reasoning: str = Field(
        ..., min_length=10,
        description="Logical reasoning or counter-evidence justifying this stance.",
    )


class VisionaryOutput(BaseModel):
    """Structured output from the Visionary LLM call."""

    content: str = Field(
        ..., min_length=10,
        description="The lateral idea - unconventional, creative, yet plausible.",
    )
    related_claim_ids: list[str] = Field(
        default_factory=list,
        description="IDs of existing claims this idea builds upon.",
    )
    novelty_rationale: str = Field(
        ..., min_length=10,
        description="Why this idea is novel yet actionable.",
    )


class SynthesizerOutput(BaseModel):
    """Structured output from the Synthesizer LLM call."""

    content: str = Field(
        ..., min_length=10,
        description="Merged perspective that integrates all agent contributions.",
    )
    incorporated_claim_ids: list[str] = Field(
        default_factory=list,
        description="IDs of claims incorporated.",
    )
    resolved_tensions: list[str] = Field(
        default_factory=list,
        description="Contradictions or disagreements resolved in this synthesis.",
    )
    remaining_tensions: list[str] = Field(
        default_factory=list,
        description="Contradictions still unresolved after this synthesis.",
    )
    confidence: Confidence = Field(
        default=Confidence.MEDIUM,
    )
