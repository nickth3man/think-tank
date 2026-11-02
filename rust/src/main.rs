//! CLI entry point, mirroring `main.py`.
//!
//! Reads provider credentials from the environment, seeds the vector store with
//! the dummy knowledge-base documents when it is empty, then runs a full
//! deliberation cycle on the topic given as arguments (or prompted for).

use std::io::{self, Write};
use std::time::{SystemTime, UNIX_EPOCH};

use think_tank::graph::{run, Observer, RunServices};
use think_tank::kb::SEED_DOCUMENTS;
use think_tank::llm::{resolve_embedding_provider, resolve_provider};
use think_tank::print::{render_state, separator};
use think_tank::runner::{initial_state, prepare_run, PrepareError};
use think_tank::state::ThinkTankState;
use think_tank::telemetry::{recorder, run_scope, span};

/// Prints each distinct round as the loop advances, like the value stream.
struct CliObserver {
    seen_rounds: Vec<u32>,
}

impl Observer for CliObserver {
    fn on_round(&mut self, state: &ThinkTankState) {
        if self.seen_rounds.contains(&state.current_round) {
            return;
        }
        self.seen_rounds.push(state.current_round);
        print!("{}", render_state(state));
        let _ = io::stdout().flush();
    }
}

fn prompt_topic() -> String {
    print!("Enter the topic or task for the Think Tank: ");
    let _ = io::stdout().flush();
    let mut line = String::new();
    let _ = io::stdin().read_line(&mut line);
    line.trim().to_string()
}

fn main() {
    let prepared = match prepare_run() {
        Ok(prepared) => prepared,
        Err(PrepareError::Missing(exc)) => {
            eprintln!(
                "Missing credentials: {}. Export them in your shell (e.g. ~/.zshenv) \
                 or select another provider with THINK_TANK_PROVIDER.",
                exc
            );
            std::process::exit(1);
        }
        Err(other) => {
            eprintln!("{}", other);
            std::process::exit(1);
        }
    };

    let chat = resolve_provider(None, true).expect("chat provider");
    let embeddings = resolve_embedding_provider(None).expect("embedding provider");
    println!(
        "[config] chat provider={} embeddings provider={}",
        chat.name, embeddings.name
    );
    if prepared.seeded {
        println!(
            "[seed] Populated the vector store with {} dummy documents.\n",
            SEED_DOCUMENTS.len()
        );
    } else {
        println!("[seed] Vector collection already has documents — skipping seed.\n");
    }

    let args: Vec<String> = std::env::args().skip(1).collect();
    let topic = if args.is_empty() {
        prompt_topic()
    } else {
        args.join(" ").trim().to_string()
    };
    if topic.is_empty() {
        eprintln!("No topic provided. Pass it as a CLI argument or enter it when prompted.");
        std::process::exit(1);
    }

    let state = initial_state(&topic, None);
    print!("{}", separator(&format!("THINK TANK — Topic: {}", topic)));
    let _ = io::stdout().flush();

    let services = RunServices {
        vector_store: prepared.vector_store,
    };
    let run_id = format!(
        "cli_{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0)
    );
    let mut observer = CliObserver {
        seen_rounds: Vec::new(),
    };
    let outcome = run_scope(&run_id, || {
        span("graph.stream", "graph", || {
            run(state, &services, &mut observer)
        })
    });

    match outcome {
        Ok(final_state) => {
            if final_state.synthesis.is_none() {
                eprintln!("deliberation ended without a synthesis");
                std::process::exit(1);
            }
            print!("{}", separator("DELIBERATION COMPLETE"));
            if recorder().enabled() {
                println!("{}", recorder().report(40, Some(&run_id)));
            }
        }
        Err(err) => {
            eprintln!("deliberation failed: {}", err);
            std::process::exit(1);
        }
    }
}
