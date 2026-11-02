"""think_tank/telemetry.py — Span recorder for latency and cost attribution.

Enable with ``THINK_TANK_PROFILE=1``; ``main.py`` prints the report at exit and
``app.py`` exposes it on ``/profile``. Spans nest, so a graph-node span contains
the LLM, embedding and vector-store spans it issued.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

#: Identifier of the run currently executing in this task, if any. A ContextVar
#: is correct under LangGraph's async tasks and thread pools, where a plain
#: module global would attribute concurrent runs to each other.
_current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "think_tank_run_id", default=None
)


def current_run() -> str | None:
    """The run id spans are currently tagged with, or ``None`` outside a run."""
    return _current_run.get()


@contextlib.contextmanager
def run_scope(run_id: str):
    """Tag every span created inside this block with ``run_id``."""
    token = _current_run.set(run_id)
    try:
        yield run_id
    finally:
        _current_run.reset(token)


def _env_enabled() -> bool:
    return os.getenv("THINK_TANK_PROFILE") not in (None, "", "0")


@dataclass(slots=True)
class Span:
    """One measured unit of work."""

    name: str
    kind: str
    start: float
    end: float = 0.0
    depth: int = 0
    run_id: str | None = None
    attrs: dict[str, object] = field(default_factory=dict)
    error: str | None = None

    @property
    def duration(self) -> float:
        return (self.end or time.perf_counter()) - self.start


class Recorder:
    """Thread-safe collector of spans for one process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.spans: list[Span] = []
        self._depth = threading.local()
        #: Runtime override; ``None`` means "follow THINK_TANK_PROFILE".
        self._force: bool | None = None

    def enable(self, value: bool = True) -> None:
        """Force recording on or off regardless of the environment."""
        self._force = value

    def enabled(self) -> bool:
        return self._force if self._force is not None else _env_enabled()

    @contextlib.contextmanager
    def span(self, name: str, kind: str, **attrs: object):
        if not self.enabled():
            yield None
            return
        depth = getattr(self._depth, "value", 0)
        span = Span(
            name=name,
            kind=kind,
            start=time.perf_counter(),
            depth=depth,
            run_id=current_run(),
            attrs=dict(attrs),
        )
        self._depth.value = depth + 1
        try:
            yield span
        except Exception as exc:
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._depth.value = depth
            span.end = time.perf_counter()
            with self._lock:
                self.spans.append(span)

    def reset(self, run_id: str | None = None) -> None:
        """Drop spans. With ``run_id``, drop only that run's spans.

        Concurrent websocket clients run graphs simultaneously, so a blanket
        clear would delete a peer's in-flight measurements.
        """
        with self._lock:
            if run_id is None:
                self.spans.clear()
            else:
                self.spans = [s for s in self.spans if s.run_id != run_id]

    def _select(self, run_id: str | None) -> list[Span]:
        with self._lock:
            spans = list(self.spans)
        return spans if run_id is None else [s for s in spans if s.run_id == run_id]

    def exclusive_totals(self, run_id: str | None = None) -> dict[str, float]:
        """Time per kind with nested children subtracted, so shares sum to ~100%.

        A span that contains other spans (``embed_query`` wrapping an HTTP call,
        a graph node wrapping an LLM call) would otherwise be counted twice.
        """
        spans = self._select(run_id)
        out: dict[str, float] = defaultdict(float)
        for span in spans:
            out[span.kind] += span.duration
        # Spans are appended when they close, so ordering is by end time, not
        # start. Subtract every child's overlap from its true parent by interval
        # containment rather than relying on list adjacency.
        ordered = sorted(spans, key=lambda s: (s.start, -s.depth))
        for parent in ordered:
            if not parent.end:
                continue
            for child in ordered:
                if child is parent or not child.end:
                    continue
                if (
                    child.start >= parent.start
                    and child.end <= parent.end
                    and (child.depth > parent.depth)
                ):
                    out[parent.kind] -= child.duration
        return {k: max(0.0, v) for k, v in out.items()}

    def report(self, *, limit: int = 40, run_id: str | None = None) -> str:
        """Human-readable profile: slowest spans plus per-kind breakdown."""
        spans = self._select(run_id)
        if not spans:
            return "profile: no spans recorded (set THINK_TANK_PROFILE=1)."

        by_kind: dict[str, list[Span]] = defaultdict(list)
        for span in spans:
            by_kind[span.kind].append(span)

        lines = ["", "=" * 78, "  PROFILE", "=" * 78]
        total_wall = max((s.end for s in spans), default=0.0) - min(
            (s.start for s in spans), default=0.0
        )
        lines.append(f"  wall clock (sum of roots) ... {total_wall:8.2f}s")
        exclusive = self.exclusive_totals(run_id)
        for kind in sorted(by_kind, key=lambda k: -exclusive.get(k, 0.0)):
            group = by_kind[kind]
            elapsed = exclusive.get(kind, 0.0)
            share = (elapsed / total_wall * 100) if total_wall else 0.0
            lines.append(f"  {kind:<24} n={len(group):<4} {elapsed:8.2f}s  {share:5.1f}% of wall")

        slowest = sorted(spans, key=lambda s: s.duration, reverse=True)[:limit]
        lines.append("")
        lines.append(f"  slowest spans (top {len(slowest)}):")
        for span in slowest:
            indent = "  " * (span.depth + 1)
            attrs = " ".join(f"{k}={v}" for k, v in span.attrs.items() if v not in (None, ""))
            err = f"  !! {span.error}" if span.error else ""
            lines.append(f"  {span.duration:8.2f}s {indent}{span.name} [{span.kind}] {attrs}{err}")
        lines.append("=" * 78)
        return "\n".join(lines)


RECORDER = Recorder()


def span(name: str, kind: str, **attrs: object):
    """Record a span under ``kind``; a no-op unless profiling is enabled."""
    return RECORDER.span(name, kind, **attrs)
