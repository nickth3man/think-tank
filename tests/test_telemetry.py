"""Tests for think_tank/telemetry.py — span recording and profile accounting."""

from __future__ import annotations

import time

import pytest

from think_tank.telemetry import Recorder, Span, current_run, run_scope


@pytest.fixture
def recorder() -> Recorder:
    r = Recorder()
    r.enable(True)
    return r


class TestRecording:
    def test_disabled_records_nothing(self) -> None:
        r = Recorder()
        r.enable(False)
        with r.span("x", "node"):
            pass
        assert r.spans == []

    def test_span_is_recorded_with_duration(self, recorder: Recorder) -> None:
        with recorder.span("work", "node", round=1):
            time.sleep(0.01)
        (span,) = recorder.spans
        assert span.name == "work"
        assert span.kind == "node"
        assert span.attrs["round"] == 1
        assert span.duration >= 0.01

    def test_error_is_captured_and_reraised(self, recorder: Recorder) -> None:
        with pytest.raises(ValueError, match="boom"), recorder.span("bad", "llm"):
            raise ValueError("boom")
        assert recorder.spans[0].error == "ValueError: boom"

    def test_depth_tracks_nesting(self, recorder: Recorder) -> None:
        with recorder.span("outer", "node"):
            with recorder.span("inner", "llm"):
                pass
        depths = {s.name: s.depth for s in recorder.spans}
        assert depths == {"outer": 0, "inner": 1}

    def test_reset_clears_spans(self, recorder: Recorder) -> None:
        with recorder.span("x", "node"):
            pass
        recorder.reset()
        assert recorder.spans == []


class TestExclusiveTotals:
    """Nested spans must not double-count, or the profile misattributes time."""

    def test_child_time_is_subtracted_from_parent(self, recorder: Recorder) -> None:
        with recorder.span("outer", "node"):
            with recorder.span("inner", "llm"):
                time.sleep(0.05)
        totals = recorder.exclusive_totals()
        assert totals["llm"] == pytest.approx(0.05, abs=0.02)
        assert totals["node"] < totals["llm"]

    def test_counts_by_start_not_by_close_order(self, recorder: Recorder) -> None:
        # Two siblings that close out of order must not corrupt the parent total.
        with recorder.span("parent", "node"):
            with recorder.span("first", "llm"):
                time.sleep(0.03)
            with recorder.span("second", "embedding"):
                time.sleep(0.03)
        totals = recorder.exclusive_totals()
        assert totals["node"] < totals["llm"] + totals["embedding"]
        assert totals["llm"] == pytest.approx(0.03, abs=0.02)
        assert totals["embedding"] == pytest.approx(0.03, abs=0.02)

    def test_totals_are_never_negative(self, recorder: Recorder) -> None:
        with recorder.span("outer", "node"):
            with recorder.span("inner", "llm"):
                pass
        assert all(v >= 0 for v in recorder.exclusive_totals().values())


class TestReport:
    def test_empty_report_explains_how_to_enable(self) -> None:
        assert "THINK_TANK_PROFILE" in Recorder().report()

    def test_report_lists_slowest_first(self, recorder: Recorder) -> None:
        with recorder.span("slow", "node"):
            time.sleep(0.02)
        with recorder.span("fast", "llm"):
            pass
        report = recorder.report()
        assert report.index("slow") < report.index("fast")

    def test_report_includes_attributes_and_errors(self, recorder: Recorder) -> None:
        with pytest.raises(RuntimeError), recorder.span("failing", "llm", model="m"):
            raise RuntimeError("nope")
        report = recorder.report()
        assert "model=m" in report
        assert "RuntimeError: nope" in report


class TestRuntimeToggle:
    def test_enable_overrides_environment(self) -> None:
        r = Recorder()
        r.enable(True)
        assert r.enabled()
        r.enable(False)
        assert not r.enabled()

    def test_span_duration_uses_now_when_open(self) -> None:
        span = Span(name="open", kind="node", start=time.perf_counter() - 0.01)
        assert span.duration >= 0.01


class TestRunIsolation:
    """Concurrent runs share one Recorder, so spans must be attributable.

    `app.py` serves many websocket clients from one process and streams graphs
    concurrently. A blanket reset would delete a peer's in-flight spans, and an
    untagged report would blend two runs into one meaningless wall clock.
    """

    def test_spans_are_tagged_with_the_active_run(self, recorder: Recorder) -> None:
        with run_scope("run-a"), recorder.span("work", "node"):
            pass
        assert recorder.spans[0].run_id == "run-a"

    def test_untagged_outside_a_run_scope(self, recorder: Recorder) -> None:
        with recorder.span("work", "node"):
            pass
        assert recorder.spans[0].run_id is None

    def test_report_filters_to_one_run(self, recorder: Recorder) -> None:
        with run_scope("a"), recorder.span("only-a", "node"):
            pass
        with run_scope("b"), recorder.span("only-b", "node"):
            pass
        report_a = recorder.report(run_id="a")
        assert "only-a" in report_a
        assert "only-b" not in report_a

    def test_reset_one_run_leaves_the_other(self, recorder: Recorder) -> None:
        with run_scope("a"), recorder.span("only-a", "node"):
            pass
        with run_scope("b"), recorder.span("only-b", "node"):
            pass
        recorder.reset("a")
        assert [s.name for s in recorder.spans] == ["only-b"]

    def test_exclusive_totals_are_per_run(self, recorder: Recorder) -> None:
        with run_scope("a"):
            with recorder.span("outer", "node"):
                with recorder.span("inner", "llm"):
                    time.sleep(0.03)
        assert "llm" in recorder.exclusive_totals("a")
        assert recorder.exclusive_totals("nonexistent") == {}

    def test_scope_is_restored_after_exit(self, recorder: Recorder) -> None:
        with run_scope("a"):
            pass
        assert current_run() is None
