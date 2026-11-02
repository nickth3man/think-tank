"""HISTORICAL — reference only. This script cannot run any more.

It imported the Python ``think_tank`` package, which the Rust rewrite deleted
after ``python_golden.json`` was recorded. It is kept so the provenance of that
fixture is auditable: anyone can see exactly which seams were stubbed and how
the deterministic embedding and id normalisation were defined.

Original purpose: record golden fixtures from the Python implementation.

The Python tree is the reference oracle for the Rust rewrite. This script drives
the *real* Python node bodies and the *real* arbiter with two seams replaced by
deterministic doubles:

* ``agent_structured_llm`` — returns a scripted ``*Output`` per call, in order.
* ``researcher._get_embedder`` / ``retrieve`` — a deterministic hash embedding
  and a fixed evidence string (Chroma itself is out of parity scope: the Rust
  port keeps the three vector-store semantics on a JSON collection, so it cannot
  be byte-compared with Chroma's HNSW index).

Everything else — prompt construction, hydration, arbiter scoring, routing,
CLI rendering — runs unmodified, so its output is a faithful reference for the
Rust implementation to match.

Run from the repo root:  uv run python rust/fixtures/record_python_golden.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import think_tank.agents.researcher as researcher_mod  # noqa: E402
import think_tank.agents.skeptic as skeptic_mod
import think_tank.agents.synthesizer as synthesizer_mod
import think_tank.agents.visionary as visionary_mod
from think_tank.graph import build_think_tank_graph  # noqa: E402
from think_tank.runner import initial_state
from think_tank.schemas import (
    Confidence,
    ResearcherOutput,
    SkepticOutput,
    Stance,
    SynthesizerOutput,
    VisionaryOutput,
)
from think_tank.state import ThinkTankState

OUT = ROOT / "rust" / "fixtures" / "python_golden.json"

# ---------------------------------------------------------------------------
# Deterministic embedding: FNV-1a per dimension, mapped to [-1, 1].
# The Rust stub server implements the same function.
# ---------------------------------------------------------------------------

DIMS = 8
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK = 0xFFFFFFFFFFFFFFFF


def fnv1a(data: bytes) -> int:
    h = FNV_OFFSET
    for byte in data:
        h ^= byte
        h = (h * FNV_PRIME) & MASK
    return h


def embed(text: str) -> list[float]:
    out = []
    for i in range(DIMS):
        h = fnv1a(f"{i}:{text}".encode())
        value = (h / 2**64) * 2.0 - 1.0
        out.append(value)
    return out


class HashEmbedder:
    def embed_query(self, text: str) -> list[float]:
        return embed(text)


# ---------------------------------------------------------------------------
# Scripted structured LLM
# ---------------------------------------------------------------------------

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def substitute(value, first_claim_id: str):
    """Replace ``__FIRST_CLAIM_ID__`` placeholders inside a scripted payload."""
    if isinstance(value, str):
        return value.replace("__FIRST_CLAIM_ID__", first_claim_id)
    if isinstance(value, list):
        return [substitute(v, first_claim_id) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, first_claim_id) for k, v in value.items()}
    return value


BUILDERS = {
    "Researcher": ResearcherOutput,
    "Skeptic": SkepticOutput,
    "Visionary": VisionaryOutput,
    "Synthesizer": SynthesizerOutput,
}


class ScriptedLLM:
    """One scripted structured call: returns the next payload for this agent."""

    def __init__(self, script: list[dict], cursor: dict[str, int]) -> None:
        self.script = script
        self.cursor = cursor

    def invoke(self, messages, **_kwargs):
        human = messages[-1].content
        match = UUID_RE.search(human)
        first_claim_id = match.group(0) if match else ""
        # The next unconsumed script entry decides which schema fires.
        index = self.cursor["i"]
        entry = self.script[index]
        self.cursor["i"] = index + 1
        payload = substitute(entry["payload"], first_claim_id)
        return BUILDERS[entry["schema"]].model_validate(payload)


def make_structured_llm(script: list[dict], cursor: dict[str, int]):
    def factory(agent, config, schema, *, temperature=0.0):
        return ScriptedLLM(script, cursor)

    return factory


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

EVIDENCE = (
    "Remote work has been shown to increase productivity for knowledge workers by 13%.\n"
    "Communication overhead increases by approximately 30% in fully remote teams."
)

CLAIM_TEXT = (
    "Evidence indicates remote work reliably raises individual productivity, driven by "
    "quieter work environments and fewer sick days across large employee samples."
)
CHALLENGE_TEXT = (
    "The productivity figure comes from knowledge workers only, so generalising it to all "
    "roles overstates the case and hides coordination costs."
)
IDEA_TEXT = (
    "Treat the office as an intermittently scheduled collaboration venue rather than a daily "
    "default, letting teams reserve dense weeks for coordination-heavy work."
)
SYNTH_TEXT = (
    "Remote work raises individual throughput while raising coordination cost; the defensible "
    "position is a scheduled hybrid where focus work is remote and coordination is co-located."
)

# Two distinct claims so the round-0 pairwise term is non-trivial in scenario 2.
CLAIM_TEXT_ALT = (
    "Coordination overhead, not individual output, is the binding constraint: dense "
    "synchronous blocks are what remote schedules actually erode."
)


def claim_payload(content: str, confidence: str = "high") -> dict:
    return {
        "content": content,
        "dimensions": {"feasibility": "high", "risk": "moderate", "impact": "high"},
        "confidence": confidence,
        "evidence_summary": "Two large-sample studies agree on direction.",
    }


def skeptic_payload(stance: str, content: str) -> dict:
    return {
        "target_claim_id": "__FIRST_CLAIM_ID__",
        "stance": stance,
        "content": content,
        "reasoning": "Scope of the cited samples is narrower than the claim asserts.",
    }


def visionary_payload(content: str) -> dict:
    return {
        "content": content,
        "related_claim_ids": ["__FIRST_CLAIM_ID__"],
        "novelty_rationale": "Reframes the office as a scheduling primitive, not a location.",
    }


def synthesizer_payload(content: str, remaining: list[str]) -> dict:
    return {
        "content": content,
        "incorporated_claim_ids": ["__FIRST_CLAIM_ID__"],
        "resolved_tensions": ["Individual output versus coordination cost, resolved as scoped."],
        "remaining_tensions": remaining,
        "confidence": "medium",
    }


def script_for(scenario: str) -> list[dict]:
    """The LLM calls one deliberation makes, in execution order."""
    if scenario == "converge":
        # Round 0 diverges (score ~0.10), round 1 converges (score 1.00).
        return [
            {"schema": "Researcher", "payload": claim_payload(CLAIM_TEXT)},
            {"schema": "Skeptic", "payload": skeptic_payload("oppose", CHALLENGE_TEXT)},
            {"schema": "Visionary", "payload": visionary_payload(IDEA_TEXT)},
            {
                "schema": "Synthesizer",
                "payload": synthesizer_payload(SYNTH_TEXT, ["Coordination cost is unquantified."]),
            },
            {"schema": "Researcher", "payload": claim_payload(CLAIM_TEXT)},
            {"schema": "Skeptic", "payload": skeptic_payload("refine", CHALLENGE_TEXT)},
            {"schema": "Visionary", "payload": visionary_payload(IDEA_TEXT)},
            {
                "schema": "Synthesizer",
                "payload": synthesizer_payload(SYNTH_TEXT, []),
            },
        ]
    if scenario == "forced":
        # Threshold is unreachable, so max_rounds forces a best-effort synthesis.
        return [
            {"schema": "Researcher", "payload": claim_payload(CLAIM_TEXT_ALT)},
            {"schema": "Skeptic", "payload": skeptic_payload("support", CHALLENGE_TEXT)},
            {"schema": "Visionary", "payload": visionary_payload(IDEA_TEXT)},
            {
                "schema": "Synthesizer",
                "payload": synthesizer_payload(SYNTH_TEXT, ["Coordination cost is unquantified."]),
            },
            {"schema": "Researcher", "payload": claim_payload(CLAIM_TEXT)},
            {"schema": "Skeptic", "payload": skeptic_payload("oppose", CHALLENGE_TEXT)},
            {"schema": "Visionary", "payload": visionary_payload(IDEA_TEXT)},
            {"schema": "Synthesizer", "payload": synthesizer_payload(SYNTH_TEXT, [])},
        ]
    raise ValueError(scenario)


SCENARIOS = [
    {
        "name": "converge",
        "topic": "Should companies adopt fully remote work?",
        "config": {"alignment_threshold": 0.65, "min_rounds": 2, "max_rounds": 6},
    },
    {
        "name": "forced",
        "topic": "Should companies adopt fully remote work?",
        "config": {"alignment_threshold": 1.01, "min_rounds": 2, "max_rounds": 2},
    },
]


# ---------------------------------------------------------------------------
# Normalisation — ids and timestamps are generated per run, so they are
# canonicalised before comparison. Everything else stays verbatim.
# ---------------------------------------------------------------------------


def normalise(value, id_map: dict[str, str]):
    if isinstance(value, str):
        # Full ids first, then their 8-character prefixes: the CLI renders
        # `target_claim_id[:8]`, which must also become deterministic.
        for uuid, token in id_map.items():
            value = value.replace(uuid, token)
        for uuid, token in id_map.items():
            value = value.replace(uuid[:8], token[:8])
        return value
    if isinstance(value, list):
        return [normalise(v, id_map) for v in value]
    if isinstance(value, dict):
        out = {}
        for key, raw in value.items():
            if key == "created_at":
                out[key] = "<timestamp>"
            elif key == "id":
                out[key] = id_map.get(raw, raw)
            else:
                out[key] = normalise(raw, id_map)
        return out
    return value


def build_id_map(state: ThinkTankState) -> dict[str, str]:
    """Assign stable tokens in first-appearance order."""
    id_map: dict[str, str] = {}

    def register(value: str) -> None:
        if value and value not in id_map:
            # Token keeps the 8-hex-char prefix shape the CLI truncates to, so
            # `target_claim_id[:8]` normalises to the same text on both sides.
            index = len(id_map) + 1
            id_map[value] = f"{index:08x}-0000-4000-8000-000000000000"

    for claim in state["claims"]:
        register(claim.id)
    for challenge in state["challenges"]:
        register(challenge.id)
    for idea in state["expansions"]:
        register(idea.id)
    for attempt in state["syntheses"]:
        register(attempt.id)
    if state["expansion"] is not None:
        register(state["expansion"].id)
    if state["synthesis"] is not None:
        register(state["synthesis"].id)
    return id_map


def run_scenario(spec: dict) -> dict:
    script = script_for(spec["name"])
    cursor = {"i": 0}
    factory = make_structured_llm(script, cursor)

    researcher_mod.agent_structured_llm = factory
    skeptic_mod.agent_structured_llm = factory
    visionary_mod.agent_structured_llm = factory
    synthesizer_mod.agent_structured_llm = factory
    researcher_mod._get_embedder = lambda: HashEmbedder()
    researcher_mod.retrieve = lambda topic, k=5: EVIDENCE

    graph = build_think_tank_graph()
    state = initial_state(spec["topic"], spec["config"])

    rendered_rounds: list[str] = []
    seen: set[int] = set()
    final: ThinkTankState | None = None
    from main import _print_state

    import io
    import contextlib

    for event in graph.stream(state, stream_mode="values"):
        round_num = event.get("current_round", 0)
        if round_num not in seen:
            seen.add(round_num)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                _print_state(event)
            rendered_rounds.append(buffer.getvalue())
        final = event

    assert final is not None
    assert cursor["i"] == len(script), f"consumed {cursor['i']} of {len(script)} scripted calls"

    id_map = build_id_map(final)
    trace = {
        "claims": [normalise(c.model_dump(mode="json"), id_map) for c in final["claims"]],
        "challenges": [normalise(c.model_dump(mode="json"), id_map) for c in final["challenges"]],
        "expansions": [normalise(e.model_dump(mode="json"), id_map) for e in final["expansions"]],
        "syntheses": [normalise(s.model_dump(mode="json"), id_map) for s in final["syntheses"]],
        "expansion": normalise(final["expansion"].model_dump(mode="json"), id_map)
        if final["expansion"]
        else None,
        "synthesis": normalise(final["synthesis"].model_dump(mode="json"), id_map)
        if final["synthesis"]
        else None,
        "current_round": final["current_round"],
        "alignment_score": final["alignment_score"],
        "evidence": final["evidence"],
    }
    return {
        "name": spec["name"],
        "topic": spec["topic"],
        "config": spec["config"],
        "evidence_seed": EVIDENCE,
        "script": script,
        "rendered_rounds": [normalise(text, id_map) for text in rendered_rounds],
        "expected": trace,
    }


def main() -> None:
    results = [run_scenario(spec) for spec in SCENARIOS]
    OUT.write_text(json.dumps({"scenarios": results}, indent=2) + "\n")
    print(f"wrote {OUT} ({len(results)} scenarios)")
    for result in results:
        trace = result["expected"]
        print(
            f"  {result['name']}: rounds={trace['current_round']} "
            f"score={trace['alignment_score']} "
            f"claims={len(trace['claims'])} syntheses={len(trace['syntheses'])}"
        )


if __name__ == "__main__":
    sys.exit(main())
