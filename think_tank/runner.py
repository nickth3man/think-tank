"""think_tank/runner.py — Run setup shared by every entry point.

Both ``main.py`` (CLI) and ``app.py`` (dashboard) need the same three things
before a deliberation: the convergence config defaults, the provider credential
check, and a seeded vector store. Keeping that here means the defaults exist
once and are covered by ``tests/test_runner.py`` instead of being duplicated in
two root scripts that the coverage config does not measure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from think_tank.kb import aseed_if_empty, get_vector_store, seed_if_empty
from think_tank.llm import missing_credentials
from think_tank.state import ThinkTankState
from think_tank.telemetry import span

if TYPE_CHECKING:
    from langchain_chroma import Chroma

# Convergence defaults for a deliberation run. Callers may override any key by
# passing their own ``config`` to :func:`initial_state`.
DEFAULT_CONFIG: dict[str, float | int] = {
    "alignment_threshold": 0.65,
    "min_rounds": 2,
    "max_rounds": 6,
}


class MissingCredentialsError(RuntimeError):
    """Raised when the configured chat or embedding provider has no API key."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(", ".join(missing))


@dataclass(frozen=True)
class PreparedRun:
    """Result of :func:`prepare_run` — a live vector store, seeded if needed."""

    vector_store: Chroma
    seeded: bool


def initial_state(topic: str, config: dict | None = None) -> ThinkTankState:
    """Build the state a deliberation starts from.

    ``config`` overrides individual keys of :data:`DEFAULT_CONFIG`; the caller's
    dict is copied, never mutated.
    """
    return {
        "topic": topic,
        "config": dict(DEFAULT_CONFIG, **(config or {})),
        "claims": [],
        "challenges": [],
        "expansions": [],
        "syntheses": [],
        "current_round": 0,
        "alignment_score": 0.0,
        "expansion": None,
        "synthesis": None,
        "evidence": "",
    }


def require_credentials() -> None:
    """Raise :class:`MissingCredentialsError` when a provider key is unset."""
    missing = missing_credentials()
    if missing:
        raise MissingCredentialsError(missing)


def prepare_run() -> PreparedRun:
    """Check credentials, open the vector store, and seed it when empty.

    Blocking variant for synchronous callers (the CLI). Async callers must use
    :func:`aprepare_run` — seeding embeds every document, which would stall the
    event loop for every other websocket client.
    """
    require_credentials()
    with span("startup.vector_store", "startup"):
        vector_store = get_vector_store()
    with span("startup.seed", "startup"):
        seeded = seed_if_empty(vector_store)
    return PreparedRun(vector_store=vector_store, seeded=seeded)


async def aprepare_run() -> PreparedRun:
    """Async variant of :func:`prepare_run` for the dashboard's websocket handler."""
    require_credentials()
    with span("startup.vector_store", "startup"):
        vector_store = get_vector_store()
    with span("startup.seed", "startup"):
        seeded = await aseed_if_empty(vector_store)
    return PreparedRun(vector_store=vector_store, seeded=seeded)
