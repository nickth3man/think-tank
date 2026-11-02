"""think_tank/dashboard/server.py — FastAPI app for the observability dashboard.

Routes:

* ``GET /``            — the single-page dashboard (``web/index.html``)
* ``GET /healthz``     — liveness probe
* ``GET /profile``     — latency spans recorded by :mod:`think_tank.telemetry`
* ``WS  /observe``     — one websocket per client; streams a live deliberation

Run with::

    uv run uvicorn app:app --reload --host 0.0.0.0 --port 7860

or ``python app.py`` from the repo root.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from think_tank.dashboard.events import NODE_TO_AGENT, StreamAdapter, event, payload_size
from think_tank.runner import MissingCredentialsError, aprepare_run, initial_state
from think_tank.telemetry import RECORDER, run_scope

# ``web/index.html`` beside the package, reachable without an install (the
# project is intentionally unpackaged flat-layout; see docs/codebase-organization-research.md).
INDEX_PATH = Path(__file__).resolve().parents[2] / "web" / "index.html"


def _load_index() -> str:
    try:
        return INDEX_PATH.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - packaging error, not a request path
        raise RuntimeError(f"dashboard frontend missing at {INDEX_PATH}") from exc


INDEX_HTML = _load_index()

logger = logging.getLogger(__name__)

app = FastAPI(title="Think Tank · Observability")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/profile")
async def profile(run_id: str | None = None) -> dict:
    """Latency breakdown for one run, or for every span when ``run_id`` is omitted."""
    return {
        "exclusive_seconds": RECORDER.exclusive_totals(run_id),
        "report": RECORDER.report(limit=40, run_id=run_id),
        "enabled": RECORDER.enabled(),
        "run_id": run_id,
    }


async def _emit_node_events(
    ws: WebSocket,
    adapter: StreamAdapter,
    node_name: str,
    delta: dict | None,
    last_state: dict,
) -> dict:
    """Stream one node's enter/diff/exit events and return the merged state."""
    for ev in adapter.open_node(node_name):
        await ws.send_json(ev)

    # merge delta into our running state to compute diffs
    merged: dict = {**last_state, **(delta or {})}
    for ev in adapter.diff_state(node_name, merged):
        await ws.send_json(ev)

    for ev in adapter.close_node(node_name):
        await ws.send_json(ev)
    return merged


async def _close_quietly(ws: WebSocket) -> None:
    """Close after the client may already be gone; a failure here is not actionable."""
    try:
        await ws.close()
    except Exception:  # pylint: disable=broad-except - already disconnected
        logger.debug("websocket close failed after stream end", exc_info=True)


@app.websocket("/observe")
async def observe(ws: WebSocket) -> None:
    """One websocket per client. Client sends ``{action:'start', topic}``;
    server streams events as the LangGraph deliberation progresses."""
    await ws.accept()
    run_id = f"run_{uuid.uuid4().hex[:10]}"

    try:
        msg = await ws.receive_json()
    except WebSocketDisconnect:
        return
    if msg.get("action") != "start":
        await ws.send_json(
            event(
                "ERROR",
                "system",
                "protocol.error",
                {"reason": "expected {action:'start', topic}"},
            )
        )
        await ws.close()
        return

    topic = (msg.get("topic") or "").strip() or "Untitled deliberation"

    try:
        await aprepare_run()
    except MissingCredentialsError as exc:
        await ws.send_json(
            event(
                "ERROR",
                "system",
                "config.missing",
                {
                    "reason": f"missing credentials: {', '.join(exc.missing)}",
                    "hint": (
                        "Export these variables in your shell (e.g. ~/.zshenv) and restart, "
                        "or open /?demo=1 for a built-in trace."
                    ),
                },
            )
        )
        await ws.close()
        return
    except Exception as exc:  # vector store unavailable — run without grounding
        await ws.send_json(
            event("WARN", "system", "vector_store.seed_failed", {"reason": str(exc)})
        )

    # Lazy-import the graph so the module loads even without langgraph installed.
    try:
        from think_tank.graph import build_think_tank_graph
    except Exception as e:
        await ws.send_json(event("ERROR", "system", "import.error", {"reason": str(e)}))
        await ws.close()
        return

    graph = build_think_tank_graph()
    state = initial_state(topic)

    # Boot events
    await ws.send_json(
        event(
            "INFO",
            "system",
            "graph.compile",
            {"nodes": list(NODE_TO_AGENT.keys()), "checkpoint": "in_memory"},
        )
    )
    await ws.send_json(
        event(
            "INFO",
            "orchestrator",
            "run.start",
            {"run_id": run_id, "topic": topic, "config": state["config"]},
            edge={
                "from": "orchestrator",
                "to": "researcher",
                "kind": "dispatch",
                "size": payload_size(state),
                "rtt": 4,
                "status": "success",
            },
        )
    )

    adapter = StreamAdapter(run_id)
    last_state: dict = {**state}

    stream_error: str | None = None
    # Every span this run emits carries ``run_id``, so /profile?run_id=... can
    # separate concurrent clients and one run cannot wipe another's spans.
    with run_scope(run_id):
        try:
            async for chunk in graph.astream(state, stream_mode="updates"):
                # chunk is { node_name: state_delta }
                for node_name, delta in chunk.items():
                    last_state = await _emit_node_events(ws, adapter, node_name, delta, last_state)
        except WebSocketDisconnect:
            return
        except Exception as e:
            await ws.send_json(
                event(
                    "ERROR",
                    "system",
                    "graph.exception",
                    {"reason": str(e), "type": type(e).__name__},
                )
            )
            stream_error = str(e)

    await ws.send_json(
        event(
            "INFO",
            "system",
            "stream.end",
            {
                "run_id": run_id,
                "status": "ok" if stream_error is None else "error",
                **({"reason": stream_error} if stream_error is not None else {}),
            },
        )
    )
    await _close_quietly(ws)
