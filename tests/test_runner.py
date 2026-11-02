"""Tests for think_tank/runner.py — run setup shared by CLI and dashboard."""

from __future__ import annotations

import pytest

from think_tank import runner


def test_initial_state_uses_default_config() -> None:
    state = runner.initial_state("Should we go hybrid?")
    assert state["topic"] == "Should we go hybrid?"
    assert state["config"] == runner.DEFAULT_CONFIG
    assert state["current_round"] == 0
    assert state["alignment_score"] == 0.0
    assert state["claims"] == []
    assert state["challenges"] == []
    assert state["expansions"] == []
    assert state["syntheses"] == []
    assert state["expansion"] is None
    assert state["synthesis"] is None
    assert state["evidence"] == ""


def test_initial_state_config_override_merges_and_does_not_mutate_caller() -> None:
    overrides = {"max_rounds": 3}
    state = runner.initial_state("topic", overrides)

    assert state["config"]["max_rounds"] == 3
    assert state["config"]["alignment_threshold"] == runner.DEFAULT_CONFIG["alignment_threshold"]
    assert state["config"]["min_rounds"] == runner.DEFAULT_CONFIG["min_rounds"]
    assert overrides == {"max_rounds": 3}


def test_initial_state_config_is_a_fresh_dict_per_call() -> None:
    first = runner.initial_state("a")
    first["config"]["max_rounds"] = 99

    assert runner.initial_state("b")["config"]["max_rounds"] == runner.DEFAULT_CONFIG["max_rounds"]


def test_require_credentials_raises_with_missing_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "missing_credentials", lambda: ["OPENROUTER_API_KEY"])

    with pytest.raises(runner.MissingCredentialsError) as excinfo:
        runner.require_credentials()

    assert excinfo.value.missing == ["OPENROUTER_API_KEY"]
    assert "OPENROUTER_API_KEY" in str(excinfo.value)


def test_require_credentials_passes_when_nothing_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "missing_credentials", list)
    runner.require_credentials()  # must not raise


def test_prepare_run_seeds_and_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    store = object()
    monkeypatch.setattr(runner, "missing_credentials", list)
    monkeypatch.setattr(runner, "get_vector_store", lambda: store)
    monkeypatch.setattr(runner, "seed_if_empty", lambda vs: vs is store)

    prepared = runner.prepare_run()

    assert prepared.vector_store is store
    assert prepared.seeded is True


def test_prepare_run_reports_existing_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "missing_credentials", list)
    monkeypatch.setattr(runner, "get_vector_store", object)
    monkeypatch.setattr(runner, "seed_if_empty", lambda _vs: False)

    assert runner.prepare_run().seeded is False


async def test_aprepare_run_seeds_without_blocking_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    store = object()
    monkeypatch.setattr(runner, "missing_credentials", list)
    monkeypatch.setattr(runner, "get_vector_store", lambda: store)
    monkeypatch.setattr(runner, "seed_if_empty", _sync_seeding_is_a_bug)
    monkeypatch.setattr(runner, "aseed_if_empty", _async_seeded)

    prepared = await runner.aprepare_run()

    assert prepared.vector_store is store
    assert prepared.seeded is True


async def test_aprepare_run_checks_credentials_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "missing_credentials", lambda: ["OPENROUTER_API_KEY"])
    monkeypatch.setattr(runner, "get_vector_store", _sync_seeding_is_a_bug)

    with pytest.raises(runner.MissingCredentialsError):
        await runner.aprepare_run()


def _sync_seeding_is_a_bug(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("async path used a blocking helper")


async def _async_seeded(_store: object) -> bool:
    return True


def test_prepare_run_stops_before_touching_chroma_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode():  # pragma: no cover - must never run
        raise AssertionError("vector store opened before credential check")

    monkeypatch.setattr(runner, "missing_credentials", lambda: ["MISTRAL_API_KEY"])
    monkeypatch.setattr(runner, "get_vector_store", explode)

    with pytest.raises(runner.MissingCredentialsError):
        runner.prepare_run()
