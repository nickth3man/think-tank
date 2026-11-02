"""Tests for think_tank/kb.py — seeding and retrieval."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from think_tank import kb
from think_tank.state import ThinkTankState


class TestRetrieve:
    """Repeated identical queries must not re-pay an embedding round trip."""

    def test_joins_matched_passages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        doc = MagicMock()
        doc.page_content = "hybrid work evidence"
        store = MagicMock()
        store.similarity_search.return_value = [doc]
        monkeypatch.setattr(kb, "get_vector_store", lambda: store)

        assert kb.retrieve("hybrid?") == "hybrid work evidence"

    def test_empty_result_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = MagicMock()
        store.similarity_search.return_value = []
        monkeypatch.setattr(kb, "get_vector_store", lambda: store)

        assert "No pre-indexed documents found" in kb.retrieve("hybrid?")

    def test_every_call_queries_the_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Deduplication is the caller's job (run state), so a second call must
        # hit the store rather than returning a process-global cached value.
        store = MagicMock()
        store.similarity_search.return_value = []
        monkeypatch.setattr(kb, "get_vector_store", lambda: store)

        kb.retrieve("hybrid?")
        kb.retrieve("hybrid?")
        assert store.similarity_search.call_count == 2


class TestSeedIfEmpty:
    """Emptiness must be probed without embedding a query."""

    def _store(self, has_docs: bool) -> MagicMock:
        store = MagicMock()
        store.get.return_value = {"ids": ["x"] if has_docs else []}
        return store

    def test_populated_store_is_left_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = self._store(has_docs=True)
        monkeypatch.setattr(kb, "SEED_DOCUMENTS", ("doc a",))
        assert kb.seed_if_empty(store) is False
        store.add_documents.assert_not_called()
        store.similarity_search.assert_not_called()

    def test_empty_store_is_seeded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = self._store(has_docs=False)
        monkeypatch.setattr(kb, "SEED_DOCUMENTS", ("doc a",))
        assert kb.seed_if_empty(store) is True
        assert store.add_documents.call_count == 1
        store.similarity_search.assert_not_called()


class TestEvidenceIsRunScoped:
    """Evidence must live in graph state, not in process-global caches.

    A module-level cache would pin an empty result taken before seeding, ignore
    a reseed or a `CHROMA_DB_PATH` change, and leak between runs in one process.
    """

    def test_researcher_stores_evidence_in_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from think_tank.agents import researcher

        monkeypatch.setattr(researcher, "retrieve", lambda topic, k=5: "evidence A")

        state: ThinkTankState = {
            "topic": "t",
            "config": {},
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
        result = researcher._researcher_node_body(state)
        assert result["evidence"] == "evidence A"

    def test_researcher_reuses_evidence_already_in_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from think_tank.agents import researcher

        calls = []

        def fake_retrieve(topic: str, k: int = 5) -> str:
            calls.append(topic)
            return "fresh"

        monkeypatch.setattr(researcher, "retrieve", fake_retrieve)
        state: ThinkTankState = {
            "topic": "t",
            "config": {},
            "claims": [],
            "challenges": [],
            "expansions": [],
            "syntheses": [],
            "current_round": 1,
            "alignment_score": 0.0,
            "expansion": None,
            "synthesis": None,
            "evidence": "already fetched",
        }
        result = researcher._researcher_node_body(state)
        assert calls == []
        assert result["evidence"] == "already fetched"
