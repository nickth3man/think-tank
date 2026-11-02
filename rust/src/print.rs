//! CLI rendering, mirroring `_print_separator` / `_print_state` in `main.py`.
//!
//! `textwrap.shorten` and `textwrap.fill` are reproduced exactly so transcript
//! output can be diffed against the Python CLI.

use crate::schemas::{Challenge, Claim, LateralIdea, SynthesisAttempt};
use crate::state::ThinkTankState;

const WIDTH: usize = 72;

pub fn separator(title: &str) -> String {
    let bar = "=".repeat(WIDTH);
    format!("\n{}\n  {}\n{}\n", bar, title, bar)
}

/// Python's `" ".join(text.strip().split())`.
fn collapse_whitespace(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Python's `textwrap.shorten(text, width)` — collapse, then truncate with
/// `" [...]"` appended if it does not fit.
pub fn shorten(text: &str, width: usize) -> String {
    let collapsed = collapse_whitespace(text);
    if collapsed.chars().count() <= width {
        return collapsed;
    }
    const PLACEHOLDER: &str = " [...]";
    let words: Vec<&str> = collapsed.split(' ').collect();
    let mut kept: Vec<&str> = Vec::new();
    let mut length = 0usize;
    for word in words {
        let extra = word.chars().count() + usize::from(!kept.is_empty());
        if length + extra + PLACEHOLDER.chars().count() > width {
            break;
        }
        kept.push(word);
        length += extra;
    }
    if kept.is_empty() {
        // textwrap falls back to a bare placeholder when no word fits.
        return PLACEHOLDER.trim_start().to_string();
    }
    format!("{}{}", kept.join(" "), PLACEHOLDER)
}

/// Python's `textwrap.fill(text, width)` for the single-paragraph case.
pub fn fill(text: &str, width: usize) -> String {
    let mut lines: Vec<String> = Vec::new();
    let mut current = String::new();
    for word in text.split_whitespace() {
        let word_len = word.chars().count();
        if current.is_empty() {
            current.push_str(word);
        } else if current.chars().count() + 1 + word_len <= width {
            current.push(' ');
            current.push_str(word);
        } else {
            lines.push(std::mem::take(&mut current));
            current.push_str(word);
        }
    }
    if !current.is_empty() {
        lines.push(current);
    }
    lines.join("\n")
}

/// Everything `_print_state` prints for one round, as a string.
pub fn render_state(state: &ThinkTankState) -> String {
    let mut out = String::new();
    out.push_str(&format!(
        "\n  Round ............. {}\n",
        state.current_round
    ));
    out.push_str(&format!(
        "  Alignment score ... {:.4}\n",
        state.alignment_score
    ));

    if !state.claims.is_empty() {
        out.push_str(&format!("\n  Claims ({}):\n", state.claims.len()));
        for c in &state.claims {
            out.push_str(&render_claim(c));
        }
    }

    if !state.challenges.is_empty() {
        out.push_str(&format!("\n  Challenges ({}):\n", state.challenges.len()));
        for ch in &state.challenges {
            out.push_str(&render_challenge(ch));
        }
    }

    if !state.expansions.is_empty() {
        out.push_str(&format!(
            "\n  Lateral Ideas ({}):\n",
            state.expansions.len()
        ));
        for e in &state.expansions {
            out.push_str(&render_lateral(e));
        }
    }

    if !state.syntheses.is_empty() {
        out.push_str(&format!(
            "\n  Synthesis Attempts ({}):\n",
            state.syntheses.len()
        ));
        for s in &state.syntheses {
            out.push_str(&render_attempt(s));
        }
    }

    if let Some(synthesis) = &state.synthesis {
        out.push_str(&separator("FINAL SYNTHESIS"));
        out.push_str(&format!(
            "  Rounds taken ...... {}\n",
            synthesis.rounds_taken
        ));
        out.push_str(&format!(
            "  Alignment ......... {:.4}\n",
            synthesis.alignment_score
        ));
        out.push_str(&format!("\n  {}\n", fill(&synthesis.content, WIDTH)));
        if !synthesis.unresolved_challenges.is_empty() {
            out.push_str(&format!(
                "\n  Unresolved challenges: {}\n",
                synthesis.unresolved_challenges.len()
            ));
        }
    }

    if let Some(expansion) = &state.expansion {
        out.push_str(&format!(
            "\n  Arbiter Directive -> loop back for round {}\n",
            expansion.round
        ));
        out.push_str(&format!(
            "    Focus: {}\n",
            expansion.focus_dimensions.join(", ")
        ));
    }

    out
}

fn render_claim(c: &Claim) -> String {
    format!(
        "    [{}] round={} confidence={}\n      {}\n",
        c.agent_id,
        c.round,
        c.confidence,
        shorten(&c.content, 120)
    )
}

fn render_challenge(ch: &Challenge) -> String {
    let target: String = ch.target_claim_id.chars().take(8).collect();
    format!(
        "    [{} -> {}] target={}...\n      {}\n",
        ch.agent_id,
        ch.stance,
        target,
        shorten(&ch.content, 120)
    )
}

fn render_lateral(e: &LateralIdea) -> String {
    format!(
        "    [{}] round={}\n      {}\n",
        e.agent_id,
        e.round,
        shorten(&e.content, 120)
    )
}

fn render_attempt(s: &SynthesisAttempt) -> String {
    format!(
        "    round={} confidence={}\n      {}\n",
        s.round,
        s.confidence,
        shorten(&s.content, 120)
    )
}
