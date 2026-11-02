//! Graph state, mirroring `think_tank/state.py`.

use crate::schemas::{Challenge, Claim, Expansion, LateralIdea, Synthesis, SynthesisAttempt};

/// Full state threaded through the deliberation loop.
///
/// There are no reducers: every node clones the state, appends to the relevant
/// vector, and returns the whole new state. Appending only the new artefact
/// would overwrite history, exactly as in the Python implementation.
#[derive(Debug, Clone)]
pub struct ThinkTankState {
    pub topic: String,
    pub config: crate::runner::Config,
    pub claims: Vec<Claim>,
    pub challenges: Vec<Challenge>,
    pub expansions: Vec<LateralIdea>,
    pub syntheses: Vec<SynthesisAttempt>,
    pub evidence: String,
    pub current_round: u32,
    pub alignment_score: f64,
    pub expansion: Option<Expansion>,
    pub synthesis: Option<Synthesis>,
}

impl ThinkTankState {
    pub fn claims_for_round(&self, round: u32) -> Vec<&Claim> {
        self.claims.iter().filter(|c| c.round == round).collect()
    }

    pub fn challenges_for_round(&self, round: u32) -> Vec<&Challenge> {
        self.challenges
            .iter()
            .filter(|c| c.round == round)
            .collect()
    }

    pub fn expansions_for_round(&self, round: u32) -> Vec<&LateralIdea> {
        self.expansions
            .iter()
            .filter(|e| e.round == round)
            .collect()
    }
}
