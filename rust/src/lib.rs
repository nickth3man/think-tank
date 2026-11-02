//! Think Tank — Rust rewrite of the Python multi-agent deliberation system.

pub mod agents;
pub mod devstub;
pub mod graph;
pub mod kb;
pub mod llm;
pub mod print;
pub mod runner;
pub mod schemas;
pub mod state;
pub mod telemetry;
pub mod uireport;

pub use graph::{run, Observer, RunServices};
pub use runner::{
    initial_state, Config, DEFAULT_ALIGNMENT_THRESHOLD, DEFAULT_MAX_ROUNDS, DEFAULT_MIN_ROUNDS,
};
pub use state::ThinkTankState;
