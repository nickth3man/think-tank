//! Agent nodes, mirroring `think_tank/agents/`.

pub mod arbiter;
pub mod prompts;
pub mod researcher;
pub mod skeptic;
pub mod synthesizer;
pub mod visionary;

pub use arbiter::{arbiter_node, route_after_arbiter, Route};
pub use researcher::researcher_node;
pub use skeptic::skeptic_node;
pub use synthesizer::synthesizer_node;
pub use visionary::visionary_node;
