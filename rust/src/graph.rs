//! Graph construction and execution, mirroring `think_tank/graph.py`.
//!
//! Topology (sequential within each round):
//!
//! ```text
//! START → researcher → skeptic → visionary → synthesizer → arbiter
//!           ↑                                              ↓
//!           └──────────── (loop while diverged) ───────────┘
//!                                                        → END (converged)
//! ```
//!
//! Each node returns the whole new state. There are no reducers, so a node that
//! appended only its new artefact would drop history.

use crate::agents::{
    arbiter_node, researcher_node, route_after_arbiter, skeptic_node, synthesizer_node,
    visionary_node, Route,
};
use crate::kb::VectorStore;
use crate::state::ThinkTankState;

/// Services a node needs that the Python implementation reached through
/// module-level factories.
pub struct RunServices {
    pub vector_store: VectorStore,
}

/// Per-super-step observer, mirroring `graph.stream(stream_mode="values")`.
pub trait Observer {
    /// Called once per distinct `current_round`, with the state after that
    /// super-step. A round boundary is what the CLI prints.
    fn on_round(&mut self, state: &ThinkTankState);
}

/// No-op observer for programmatic runs.
pub struct NoObserver;

impl Observer for NoObserver {
    fn on_round(&mut self, _state: &ThinkTankState) {}
}

/// Run the deliberation loop and return the terminal state.
///
/// Mirrors the LangGraph stream: nodes run in a fixed order, and the round
/// counter only advances in the arbiter, which also decides whether to loop.
pub fn run(
    mut state: ThinkTankState,
    _services: &RunServices,
    observer: &mut dyn Observer,
) -> Result<ThinkTankState, String> {
    // `stream_mode="values"` emits the initial state before any node runs, so
    // round 0 is observable even though the arbiter owns the round counter.
    let mut seen_rounds: Vec<u32> = vec![state.current_round];
    observer.on_round(&state);
    loop {
        state = researcher_node(&state)?;
        state = skeptic_node(&state)?;
        state = visionary_node(&state)?;
        state = synthesizer_node(&state)?;
        state = arbiter_node(&state)?;

        if !seen_rounds.contains(&state.current_round) {
            seen_rounds.push(state.current_round);
            observer.on_round(&state);
        }

        match route_after_arbiter(&state) {
            Route::Researcher => continue,
            Route::End => return Ok(state),
        }
    }
}
