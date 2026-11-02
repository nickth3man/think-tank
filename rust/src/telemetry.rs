//! Span recorder, mirroring `think_tank/telemetry.py`.
//!
//! `span()` is a no-op unless `THINK_TANK_PROFILE` is set (or the recorder was
//! forced on). Spans nest through a thread-local depth counter and are tagged
//! with the current run id.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::sync::Mutex;
use std::time::Instant;

thread_local! {
    static CURRENT_RUN: RefCell<Option<String>> = const { RefCell::new(None) };
    static DEPTH: RefCell<usize> = const { RefCell::new(0) };
}

pub fn current_run() -> Option<String> {
    CURRENT_RUN.with(|c| c.borrow().clone())
}

/// Tags every span created inside the closure with `run_id`.
pub fn run_scope<T>(run_id: &str, f: impl FnOnce() -> T) -> T {
    let previous = CURRENT_RUN.with(|c| c.replace(Some(run_id.to_string())));
    let result = f();
    CURRENT_RUN.with(|c| *c.borrow_mut() = previous);
    result
}

fn env_enabled() -> bool {
    match std::env::var("THINK_TANK_PROFILE") {
        Ok(v) => !(v.is_empty() || v == "0"),
        Err(_) => false,
    }
}

/// One measured unit of work.
#[derive(Debug, Clone)]
pub struct Span {
    pub name: String,
    pub kind: String,
    pub start: Instant,
    pub end: Option<Instant>,
    pub depth: usize,
    pub run_id: Option<String>,
    pub attrs: Vec<(String, String)>,
    pub error: Option<String>,
}

impl Span {
    pub fn duration(&self) -> f64 {
        self.end
            .unwrap_or_else(Instant::now)
            .duration_since(self.start)
            .as_secs_f64()
    }

    fn attr(&mut self, key: &str, value: impl Into<String>) {
        let value = value.into();
        if let Some(slot) = self.attrs.iter_mut().find(|(k, _)| k == key) {
            slot.1 = value;
        } else {
            self.attrs.push((key.to_string(), value));
        }
    }
}

#[derive(Default)]
pub struct Recorder {
    inner: Mutex<Vec<Span>>,
    force: Mutex<Option<bool>>,
}

impl Recorder {
    pub fn enable(&self, value: bool) {
        *self.force.lock().expect("recorder lock") = Some(value);
    }

    pub fn enabled(&self) -> bool {
        match *self.force.lock().expect("recorder lock") {
            Some(v) => v,
            None => env_enabled(),
        }
    }

    /// Record a span around `f`. The span is visible to `f` so attributes can
    /// be attached while it runs, matching the Python context manager.
    pub fn span<T>(&self, name: &str, kind: &str, f: impl FnOnce(Option<&mut Span>) -> T) -> T {
        if !self.enabled() {
            return f(None);
        }
        let depth = DEPTH.with(|d| *d.borrow());
        let mut span = Span {
            name: name.to_string(),
            kind: kind.to_string(),
            start: Instant::now(),
            end: None,
            depth,
            run_id: current_run(),
            attrs: Vec::new(),
            error: None,
        };
        DEPTH.with(|d| *d.borrow_mut() = depth + 1);
        let result = f(Some(&mut span));
        DEPTH.with(|d| *d.borrow_mut() = depth);
        span.end = Some(Instant::now());
        self.inner.lock().expect("recorder lock").push(span);
        result
    }

    /// `span()` for the common case where nothing inspects the span itself.
    pub fn mark<T>(
        &self,
        name: &str,
        kind: &str,
        attrs: &[(&str, String)],
        f: impl FnOnce() -> T,
    ) -> T {
        self.span(name, kind, |span| {
            if let Some(span) = span {
                for (key, value) in attrs {
                    span.attr(key, value.clone());
                }
            }
            f()
        })
    }

    pub fn reset(&self, run_id: Option<&str>) {
        let mut spans = self.inner.lock().expect("recorder lock");
        match run_id {
            None => spans.clear(),
            Some(id) => spans.retain(|s| s.run_id.as_deref() != Some(id)),
        }
    }

    fn select(&self, run_id: Option<&str>) -> Vec<Span> {
        let spans = self.inner.lock().expect("recorder lock");
        match run_id {
            None => spans.clone(),
            Some(id) => spans
                .iter()
                .filter(|s| s.run_id.as_deref() == Some(id))
                .cloned()
                .collect(),
        }
    }

    pub fn exclusive_totals(&self, run_id: Option<&str>) -> BTreeMap<String, f64> {
        let spans = self.select(run_id);
        let mut out: BTreeMap<String, f64> = BTreeMap::new();
        for span in &spans {
            *out.entry(span.kind.clone()).or_insert(0.0) += span.duration();
        }
        let mut ordered = spans.clone();
        ordered.sort_by(|a, b| a.start.cmp(&b.start).then_with(|| b.depth.cmp(&a.depth)));
        for parent in &ordered {
            if parent.end.is_none() {
                continue;
            }
            for child in &ordered {
                if child.end.is_none() || std::ptr::eq(parent, child) {
                    continue;
                }
                let contained = child.start >= parent.start
                    && child.end <= parent.end
                    && child.depth > parent.depth;
                if contained {
                    if let Some(total) = out.get_mut(&parent.kind) {
                        *total -= child.duration();
                    }
                }
            }
        }
        for value in out.values_mut() {
            if *value < 0.0 {
                *value = 0.0;
            }
        }
        out
    }

    pub fn report(&self, limit: usize, run_id: Option<&str>) -> String {
        let spans = self.select(run_id);
        if spans.is_empty() {
            return "profile: no spans recorded (set THINK_TANK_PROFILE=1).".to_string();
        }
        let mut by_kind: BTreeMap<String, Vec<&Span>> = BTreeMap::new();
        for span in &spans {
            by_kind.entry(span.kind.clone()).or_default().push(span);
        }
        let total_wall = spans
            .iter()
            .map(|s| s.end.unwrap_or(s.start))
            .max()
            .unwrap_or_else(Instant::now)
            .duration_since(spans.iter().map(|s| s.start).min().unwrap())
            .as_secs_f64();
        let exclusive = self.exclusive_totals(run_id);
        let mut lines = vec![
            String::new(),
            "=".repeat(78),
            "  PROFILE".to_string(),
            "=".repeat(78),
            format!("  wall clock (sum of roots) ... {:8.2}s", total_wall),
        ];
        let mut kinds: Vec<(&String, &Vec<&Span>)> = by_kind.iter().collect();
        kinds.sort_by(|a, b| {
            exclusive
                .get(b.0)
                .copied()
                .unwrap_or(0.0)
                .total_cmp(&exclusive.get(a.0).copied().unwrap_or(0.0))
        });
        for (kind, group) in kinds {
            let elapsed = exclusive.get(kind).copied().unwrap_or(0.0);
            let share = if total_wall != 0.0 {
                elapsed / total_wall * 100.0
            } else {
                0.0
            };
            lines.push(format!(
                "  {:<24} n={:<4} {:8.2}s  {:5.1}% of wall",
                kind,
                group.len(),
                elapsed,
                share
            ));
        }
        let mut slowest: Vec<&Span> = spans.iter().collect();
        slowest.sort_by(|a, b| b.duration().total_cmp(&a.duration()));
        slowest.truncate(limit);
        lines.push(String::new());
        lines.push(format!("  slowest spans (top {}):", slowest.len()));
        for span in slowest {
            let indent = "  ".repeat(span.depth + 1);
            let attrs = span
                .attrs
                .iter()
                .filter(|(_, v)| !v.is_empty())
                .map(|(k, v)| format!("{}={}", k, v))
                .collect::<Vec<_>>()
                .join(" ");
            let err = span
                .error
                .as_ref()
                .map(|e| format!("  !! {}", e))
                .unwrap_or_default();
            lines.push(format!(
                "  {:8.2}s {}{} [{}] {}{}",
                span.duration(),
                indent,
                span.name,
                span.kind,
                attrs,
                err
            ));
        }
        lines.push("=".repeat(78));
        lines.join("\n")
    }
}

static RECORDER: Mutex<Option<&'static Recorder>> = Mutex::new(None);

/// The process-wide recorder.
pub fn recorder() -> &'static Recorder {
    let mut slot = RECORDER.lock().expect("recorder slot");
    if let Some(existing) = *slot {
        return existing;
    }
    let boxed: &'static Recorder = Box::leak(Box::new(Recorder::default()));
    *slot = Some(boxed);
    boxed
}

/// Record a span around `f`; a no-op unless profiling is enabled.
pub fn span<T>(name: &str, kind: &str, f: impl FnOnce() -> T) -> T {
    recorder().span(name, kind, |_| f())
}

/// Record a span carrying fixed attributes.
pub fn span_attrs<T>(name: &str, kind: &str, attrs: &[(&str, String)], f: impl FnOnce() -> T) -> T {
    recorder().mark(name, kind, attrs, f)
}
