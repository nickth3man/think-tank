"""think_tank/dashboard/events.py — LangGraph stream → dashboard event mapping.

The dashboard frontend expects events shaped like::

    {sev, agent, type, payload,
     edge?:     {from, to, kind, size, rtt, status},
     activate?: <agent_id>, deactivate?: <agent_id>}

:class:`StreamAdapter` walks the state deltas yielded by
``graph.astream(stream_mode="updates")`` and translates newly appearing
claims/challenges/ideas/syntheses into events. Node enter/exit events are
synthesized from the node-name key LangGraph returns at each step.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

NODE_TO_AGENT = {
    "researcher": "researcher",
    "skeptic": "skeptic",
    "visionary": "visionary",
    "synthesizer": "synthesizer",
    "arbiter": "arbiter",
    # Common alternates
    "research": "researcher",
    "synthesize": "synthesizer",
    "judge": "arbiter",
}


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def event(sev: str, agent: str, type_: str, payload: dict[str, Any], **extra: Any) -> dict:
    """Build one dashboard event with a millisecond UTC timestamp."""
    return {
        "sev": sev,
        "agent": agent,
        "type": type_,
        "payload": payload,
        "ts": _utc_iso(),
        **extra,
    }


def payload_size(obj: Any) -> int:
    """Serialized byte size of an event payload, or ``0`` when not serializable."""
    try:
        return len(json.dumps(obj, default=str))
    except Exception:
        return 0


class StreamAdapter:
    """Walks the LangGraph state stream and emits structured dashboard events."""

    def __init__(self, run_id: str) -> None:
        self.seen_claims: set[str] = set()
        self.run_id = run_id
        self.seen_challenges: set[str] = set()
        self.seen_ideas: set[str] = set()
        self.seen_syntheses: set[str] = set()
        self.last_round = 0
        self.node_started: dict[str, float] = {}

    @staticmethod
    def _id_of(item: Any, fallback: str) -> str:
        return getattr(item, "id", None) or getattr(item, "uid", None) or fallback

    def open_node(self, node: str) -> list[dict]:
        agent = NODE_TO_AGENT.get(node, node)
        self.node_started[agent] = time.perf_counter()
        return [
            event(
                "INFO",
                agent,
                "node.enter",
                {"node": agent, "round": self.last_round},
                activate=agent,
            )
        ]

    def close_node(self, node: str) -> list[dict]:
        agent = NODE_TO_AGENT.get(node, node)
        started = self.node_started.pop(agent, time.perf_counter())
        duration_ms = int((time.perf_counter() - started) * 1000)
        return [
            event(
                "INFO",
                agent,
                "node.exit",
                {"node": agent, "round": self.last_round, "duration_ms": duration_ms},
                deactivate=agent,
            )
        ]

    def diff_state(self, node: str, state_after: dict) -> list[dict]:
        out: list[dict] = []
        agent = NODE_TO_AGENT.get(node, node)
        rnd = state_after.get("current_round", self.last_round) or self.last_round

        if rnd != self.last_round and rnd > 0:
            out.append(event("INFO", "orchestrator", "round.start", {"round": rnd}))
            self.last_round = rnd

        # Claims
        for c in state_after.get("claims", []) or []:
            cid = self._id_of(c, f"claim_{len(self.seen_claims)}")
            if cid in self.seen_claims:
                continue
            self.seen_claims.add(cid)
            payload = {
                "id": cid,
                "round": getattr(c, "round", rnd),
                "agent_id": getattr(c, "agent_id", agent),
                "confidence": getattr(
                    getattr(c, "confidence", None), "value", str(getattr(c, "confidence", ""))
                ),
                "content": getattr(c, "content", ""),
                "evidence_summary": getattr(c, "evidence_summary", "") or "",
            }
            edge = {
                "from": "researcher",
                "to": "synthesizer",
                "kind": "claim",
                "size": payload_size(payload),
                "rtt": 5,
                "status": "success",
            }
            out.append(event("INFO", "researcher", "claim.emitted", payload, edge=edge))

        # Challenges
        for ch in state_after.get("challenges", []) or []:
            chid = self._id_of(ch, f"chal_{len(self.seen_challenges)}")
            if chid in self.seen_challenges:
                continue
            self.seen_challenges.add(chid)
            stance = getattr(getattr(ch, "stance", None), "value", str(getattr(ch, "stance", "")))
            payload = {
                "id": chid,
                "round": getattr(ch, "round", rnd),
                "agent_id": getattr(ch, "agent_id", "skeptic"),
                "stance": stance.upper(),
                "target": getattr(ch, "target_claim_id", None) or getattr(ch, "target", ""),
                "content": getattr(ch, "content", ""),
                "reasoning": getattr(ch, "reasoning", "") or "",
            }
            status = {"oppose": "error", "refine": "warn"}.get(stance.lower(), "success")
            edge = {
                "from": "skeptic",
                "to": "synthesizer",
                "kind": "challenge",
                "size": payload_size(payload),
                "rtt": 6,
                "status": status,
            }
            out.append(event("INFO", "skeptic", "challenge.emitted", payload, edge=edge))

        # Lateral ideas
        for idea in state_after.get("expansions", []) or []:
            iid = self._id_of(idea, f"idea_{len(self.seen_ideas)}")
            if iid in self.seen_ideas:
                continue
            self.seen_ideas.add(iid)
            payload = {
                "id": iid,
                "round": getattr(idea, "round", rnd),
                "agent_id": getattr(idea, "agent_id", "visionary"),
                "content": getattr(idea, "content", ""),
                "novelty_rationale": getattr(idea, "novelty_rationale", "") or "",
            }
            edge = {
                "from": "visionary",
                "to": "synthesizer",
                "kind": "lateral_idea",
                "size": payload_size(payload),
                "rtt": 7,
                "status": "success",
            }
            out.append(event("INFO", "visionary", "lateral_idea.emitted", payload, edge=edge))

        # Synthesis attempts
        for s in state_after.get("syntheses", []) or []:
            sid = self._id_of(s, f"synth_r{getattr(s, 'round', rnd)}")
            if sid in self.seen_syntheses:
                continue
            self.seen_syntheses.add(sid)
            payload = {
                "id": sid,
                "round": getattr(s, "round", rnd),
                "confidence": getattr(
                    getattr(s, "confidence", None), "value", str(getattr(s, "confidence", ""))
                ),
                "content": getattr(s, "content", ""),
                "contributing_claim_ids": list(getattr(s, "contributing_claim_ids", []) or []),
            }
            edge = {
                "from": "synthesizer",
                "to": "arbiter",
                "kind": "synthesis",
                "size": payload_size(payload),
                "rtt": 6,
                "status": "success",
            }
            out.append(event("INFO", "synthesizer", "synthesis.attempt", payload, edge=edge))

        # Alignment / convergence
        align = state_after.get("alignment_score")
        if align is not None and node == "arbiter":
            out.append(
                event(
                    "INFO",
                    "arbiter",
                    "alignment.scored",
                    {
                        "round": rnd,
                        "score": float(align),
                        "threshold": (state_after.get("config") or {}).get(
                            "alignment_threshold", 0.65
                        ),
                        "decision": "CONVERGE" if state_after.get("synthesis") else "CONTINUE",
                    },
                )
            )

        # Final synthesis → run.complete
        final = state_after.get("synthesis")
        if final is not None:
            payload = {
                "run_id": self.run_id,
                "rounds": rnd,
                "alignment_score": getattr(final, "alignment_score", align or 0.0),
                "status": "CONVERGED",
            }
            out.append(
                event(
                    "INFO",
                    "arbiter",
                    "run.complete",
                    payload,
                    edge={
                        "from": "arbiter",
                        "to": "orchestrator",
                        "kind": "control",
                        "size": payload_size(payload),
                        "rtt": 3,
                        "status": "success",
                    },
                )
            )
        return out
