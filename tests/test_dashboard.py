"""Tests for think_tank/dashboard — stream→event mapping and app wiring.

The frontend reads fixed payload keys (``payload.id``, ``payload.stance``,
``edge.from``…), so the adapter's output shape is a contract, not an internal
detail. These tests pin that contract and the "frontend is a real file" rule.
"""

from __future__ import annotations

from pathlib import Path

from think_tank.dashboard.events import NODE_TO_AGENT, StreamAdapter, event, payload_size
from think_tank.schemas import Challenge, Claim, Confidence, LateralIdea, Stance, SynthesisAttempt


def _state(**overrides) -> dict:
    base = {
        "topic": "t",
        "config": {"alignment_threshold": 0.65, "min_rounds": 2, "max_rounds": 6},
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
    return base | overrides


def test_event_carries_timestamp_and_extra_keys() -> None:
    ev = event("INFO", "researcher", "claim.emitted", {"id": "c1"}, activate="researcher")
    assert ev["sev"] == "INFO"
    assert ev["agent"] == "researcher"
    assert ev["type"] == "claim.emitted"
    assert ev["payload"] == {"id": "c1"}
    assert ev["activate"] == "researcher"
    assert ev["ts"].endswith("Z") or "+00:00" in ev["ts"]


def test_payload_size_measures_json_and_tolerates_unserializable() -> None:
    assert payload_size({"a": 1}) == len('{"a": 1}')

    circular: list = []
    circular.append(circular)  # json.dumps raises ValueError on a cycle
    assert payload_size(circular) == 0


def test_node_aliases_map_to_graph_agents() -> None:
    for name in ("researcher", "skeptic", "visionary", "synthesizer", "arbiter"):
        assert NODE_TO_AGENT[name] == name
    assert NODE_TO_AGENT["judge"] == "arbiter"


def test_open_and_close_node_emit_enter_exit_for_mapped_agent() -> None:
    adapter = StreamAdapter("run_x")
    (enter,) = adapter.open_node("judge")
    (exit_,) = adapter.close_node("judge")

    assert enter["type"] == "node.enter"
    assert enter["agent"] == "arbiter"
    assert enter["activate"] == "arbiter"
    assert exit_["type"] == "node.exit"
    assert exit_["deactivate"] == "arbiter"
    assert exit_["payload"]["duration_ms"] >= 0


def test_diff_state_emits_new_claims_once() -> None:
    adapter = StreamAdapter("run_x")
    claim = Claim(
        agent_id="researcher",
        round=1,
        content="Remote work lifts throughput.",
        embedding=[],
        confidence=Confidence.HIGH,
        dimensions={},
    )
    state = _state(claims=[claim], current_round=1)

    first = adapter.diff_state("researcher", state)
    emitted = [e for e in first if e["type"] == "claim.emitted"]
    assert len(emitted) == 1
    assert emitted[0]["payload"]["id"] == claim.id
    assert emitted[0]["payload"]["confidence"] == "high"
    assert emitted[0]["edge"]["from"] == "researcher"

    # Same claim seen again must not re-emit.
    second = adapter.diff_state("researcher", state)
    assert [e for e in second if e["type"] == "claim.emitted"] == []


def test_diff_state_maps_challenge_stance_to_edge_status() -> None:
    adapter = StreamAdapter("run_x")
    oppose = Challenge(
        agent_id="skeptic",
        target_claim_id="c1",
        round=1,
        stance=Stance.OPPOSE,
        content="The claim has no empirical support.",
        resolved=False,
    )
    (ev,) = [
        e
        for e in adapter.diff_state("skeptic", _state(challenges=[oppose]))
        if e["type"] == "challenge.emitted"
    ]
    assert ev["payload"]["stance"] == "OPPOSE"
    assert ev["edge"]["status"] == "error"


def test_diff_state_emits_round_start_on_round_change() -> None:
    adapter = StreamAdapter("run_x")
    events = adapter.diff_state("researcher", _state(current_round=3))
    assert {e["type"] for e in events} >= {"round.start"}
    assert adapter.last_round == 3


def test_diff_state_reports_convergence_on_final_synthesis() -> None:
    from think_tank.schemas import Synthesis

    adapter = StreamAdapter("run_x")
    final = Synthesis(
        content="Converged.",
        contributing_claim_ids=["c1"],
        alignment_score=0.81,
        rounds_taken=2,
        unresolved_challenges=[],
    )
    events = adapter.diff_state(
        "arbiter", _state(current_round=2, alignment_score=0.81, synthesis=final)
    )

    kinds = {e["type"] for e in events}
    assert {"alignment.scored", "run.complete"} <= kinds
    scored = next(e for e in events if e["type"] == "alignment.scored")
    assert scored["payload"]["decision"] == "CONVERGE"
    done = next(e for e in events if e["type"] == "run.complete")
    assert done["payload"]["run_id"] == "run_x"
    assert done["payload"]["status"] == "CONVERGED"


def test_diff_state_emits_ideas_and_synthesis_attempts() -> None:
    adapter = StreamAdapter("run_x")
    idea = LateralIdea(
        agent_id="visionary",
        round=1,
        content="Reframe the policy axis entirely.",
        novelty_rationale="Changes the unit of measurement.",
    )
    attempt = SynthesisAttempt(
        agent_id="synthesizer",
        round=1,
        content="Merged position so far.",
        confidence=Confidence.LOW,
    )

    events = adapter.diff_state(
        "visionary", _state(expansions=[idea], syntheses=[attempt], current_round=1)
    )
    kinds = [e["type"] for e in events]
    assert "lateral_idea.emitted" in kinds
    assert "synthesis.attempt" in kinds


def test_dashboard_serves_the_checked_in_frontend_file() -> None:
    from think_tank.dashboard import server

    repo_root = Path(__file__).resolve().parents[1]
    on_disk = (repo_root / "web" / "index.html").read_text(encoding="utf-8")

    assert server.INDEX_HTML == on_disk
    assert server.INDEX_PATH == repo_root / "web" / "index.html"
    assert "<!doctype html>" in server.INDEX_HTML


def test_dashboard_routes_include_frontend_health_and_websocket() -> None:
    from think_tank.dashboard import server

    paths = {getattr(route, "path", "") for route in server.app.routes}
    assert {"/", "/healthz", "/profile", "/observe"} <= paths
