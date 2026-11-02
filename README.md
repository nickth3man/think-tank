# Think Tank

Multi-agent deliberation system written in Rust. Four specialised agents debate a
topic in structured rounds, and an Arbiter measures whether their position has
stabilised — repeating rounds until it has, then emitting a synthesis.

## Architecture

```
START → Researcher → Skeptic → Visionary → Synthesizer → Arbiter
           ↑                                           ↓
           └────────── (loop while diverged) ──────────┘
                                                        → END (converged)
```

| Agent | Role |
|-------|------|
| **Researcher** | Grounds the discussion in evidence from a vector knowledge base |
| **Skeptic** | Stress-tests claims, exposes hidden assumptions |
| **Visionary** | Proposes unconventional lateral ideas |
| **Synthesizer** | Merges perspectives, resolves contradictions |
| **Arbiter** | Measures alignment, decides convergence or another round |

The Arbiter makes no LLM calls. Its score is `0.80 × semantic + 0.20 × (1 − opposition ratio)`,
where semantic alignment compares this round's claim embedding against previous
rounds' — it measures whether the position has stabilised, which is what
convergence means here. On convergence the final synthesis reuses the
Synthesizer's own attempt for that round.

This is a CLI application. The FastAPI observability dashboard, its `/observe`
websocket and `/profile` route that the previous implementation shipped were
**removed** in the rewrite; the CLI prints its own per-round state and latency
profile instead.

## Requirements

- A Rust toolchain (stable; the crate is edition 2021, tested on 1.99)
- Credentials for one chat provider and one embeddings provider

## Quick Start

```bash
git clone https://github.com/nickth3man/think-tank.git
cd think-tank

cargo run --release --manifest-path rust/Cargo.toml -- "Should companies adopt fully remote work?"
```

`make run TOPIC="Should companies adopt fully remote work?"` is the same thing.
The topic is passed through quoted, so `?`, `*` and multi-word text survive the
shell; with no `TOPIC` the CLI prompts for one.

A run prints each round's claims, challenges, lateral ideas and synthesis
attempts as it goes, then a final synthesis. With `THINK_TANK_PROFILE=1` it also
prints a latency profile at exit.

## Prerequisites

Credentials come from your shell environment — the app does not read `.env`.
`.env.example` lists every supported variable; append the block you need to
`~/.zshenv` and open a new shell:

```bash
cat .env.example >> ~/.zshenv   # then uncomment the keys you have
```

If a required key is missing the CLI exits non-zero and names the exact
variables it needed, rather than failing mid-run.

Providers speak the OpenAI chat-completions protocol, so switching is a matter
of exporting a different key and setting `THINK_TANK_PROVIDER`:

| Provider | Key variable | Chat | Embeddings | Default chat model |
|----------|--------------|------|------------|--------------------|
| `ollama_cloud` (default) | `OLLAMA_CLOUD_API_KEY` | ✅ | — | `deepseek-v4.1-flash` |
| `mistral` | `MISTRAL_API_KEY` | ✅ | ✅ | `mistral-small-latest` |
| `opencode` | `OPENCODE_API_KEY` | ✅ | — | `deepseek-v4.1-flash` |
| `zai` | `ZAI_API_KEY` | ✅ | — | `glm-5.3` |
| `openrouter` | `OPENROUTER_API_KEY` | ❌ | ✅ | — |

OpenRouter is deliberately **not** a chat provider: it is reserved for
embeddings. Requesting it for agent chat returns an error instead of silently
routing there.

Chat and embeddings are selected independently: `THINK_TANK_PROVIDER` drives
chat, `THINK_TANK_EMBEDDING_PROVIDER` drives retrieval (default `openrouter`).
Each knowledge-base collection is namespaced per embedding space, so switching
embedding models never mixes incompatible vectors.

## Project Structure

```
rust/
├── Cargo.toml
├── src/
│   ├── main.rs         # CLI entry point
│   ├── lib.rs          # Library surface (tests use this)
│   ├── schemas.rs      # Domain models + dimension coercion
│   ├── state.rs        # ThinkTankState (no reducers)
│   ├── llm.rs          # Provider registry + chat/embedding clients
│   ├── kb.rs           # JSON vector collection + seed documents
│   ├── graph.rs        # Loop topology + observer
│   ├── runner.rs       # Run setup (config, seed, credential check)
│   ├── telemetry.rs    # Span recording + profiling report
│   ├── print.rs        # CLI rendering
│   └── agents/
│       ├── prompts.rs  # System prompts
│       ├── researcher.rs
│       ├── skeptic.rs
│       ├── visionary.rs
│       ├── synthesizer.rs
│       └── arbiter.rs  # Arbiter node + convergence logic
├── fixtures/
│   └── python_golden.json   # Reference traces from the previous implementation
└── tests/
    ├── support/        # Local OpenAI-protocol stub server + normalisation
    ├── gate1.rs        # Real loop against the stub: ordering, state, formula
    ├── parity.rs       # Golden-fixture parity
    └── rules.rs        # Provider/model/credential rules, dimension coercion
```

## Development

```bash
make build            # cargo build
make test             # cargo test (stub-server integration + golden parity)
make fmt              # rustfmt
make fmt-check        # formatting check
make lint             # clippy, warnings denied
make check            # fmt-check + clippy + test — what CI runs
make run TOPIC="..."  # release build, then run the CLI on that topic
make clean            # remove build artifacts and the local knowledge base
```

### Tests

`make check` runs the same three gates CI does: `cargo fmt --check`,
`cargo clippy --all-targets -- -D warnings`, then `cargo test`. Tests never
touch the network and need no credentials.

| File | Covers |
|------|--------|
| `tests/gate1.rs` | The real loop against the stub server: node ordering within a round, whole-state extension (no reducers), the `0.80/0.20` arbiter formula, `min_rounds`/`max_rounds` routing, and the CLI exiting 0 |
| `tests/parity.rs` | Golden-fixture replay: identical claim/challenge/synthesis serialization, identical arbiter scores, identical per-round CLI rendering |
| `tests/rules.rs` | Provider and model precedence, credential reporting, structured-output retry, and dimension coercion |

`rust/fixtures/python_golden.json` was recorded from the Python implementation
this crate replaced. Replaying it is what pins behavioural parity. The recorder
script beside it is kept for provenance only and cannot run, since it imports
the deleted package.

CI runs the three gates on Linux and macOS.

## Tooling

| Tool | Purpose |
|------|---------|
| [Cargo](https://doc.rust-lang.org/cargo/) | Build and test runner |
| [rustfmt](https://github.com/rust-lang/rustfmt) | Formatter |
| [clippy](https://github.com/rust-lang/rust-clippy) | Lints (denied in CI) |
| [serde](https://serde.rs) | Serialization, including Python-compatible timestamps |
| [ureq](https://github.com/algesten/ureq) | Blocking HTTP client for the OpenAI protocol |
| [chrono](https://github.com/chronotope/chrono) | UTC timestamps |
| [uuid](https://github.com/uuid-rs/uuid) | Artefact identifiers |

## Configuration

Key environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `THINK_TANK_PROVIDER` | `ollama_cloud` | Chat provider (see table above) |
| `THINK_TANK_CHAT_MODEL` | provider default | Model for all agents |
| `THINK_TANK_EMBEDDING_PROVIDER` | `openrouter` | Embeddings provider |
| `THINK_TANK_EMBEDDING_MODEL` | provider default | Embeddings model |
| `THINK_TANK_<AGENT>_PROVIDER` | — | Per-agent provider override |
| `THINK_TANK_<AGENT>_MODEL` | — | Per-agent model override |
| `THINK_TANK_MAX_TOKENS` | `4096` | Runaway guard, not a length control — a tighter cap does not shorten output and can truncate a tool call |
| `THINK_TANK_REASONING_EFFORT` | provider default | Sent only to providers that accept it (`ollama_cloud`); Mistral answers HTTP 400 |
| `THINK_TANK_PROFILE` | unset | `1` prints a per-stage latency profile at exit |
| `THINK_TANK_KB_PATH` | `./kb_store` | Knowledge-base directory (one JSON collection per embedding space) |

Per-agent overrides follow config → `THINK_TANK_<AGENT>_*` → global env →
provider default. A global `THINK_TANK_CHAT_MODEL` is *not* applied to an agent
whose provider was overridden, since that would name a model the other endpoint
does not serve.

### Knowledge base

The store is one JSON collection per embedding space under `THINK_TANK_KB_PATH`,
seeded with eight dummy remote-work documents when empty and queried by cosine
similarity (top 5). The legacy `chroma_db/` directory from the previous
implementation is not read.

### Convergence parameters

These are fixed defaults in `runner` (`DEFAULT_ALIGNMENT_THRESHOLD`,
`DEFAULT_MIN_ROUNDS`, `DEFAULT_MAX_ROUNDS`). `initial_state` accepts a `Config`
overriding any of them, but **the CLI does not expose that** — `main.rs` passes
`None`, so a CLI run always uses the defaults below. Only the tests override
them, to drive the forced-synthesis path.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `alignment_threshold` | `0.65` | Minimum score to declare convergence |
| `min_rounds` | `2` | Minimum deliberation rounds |
| `max_rounds` | `6` | Hard ceiling — forces synthesis |

`Challenge.resolved` is never set by any producer, so the resolution rate is
recorded on the `arbiter.score` span but not weighted — including it capped the
score at a constant `0.75` and made every run converge on the same number.
Consequently `Synthesis.unresolved_challenges` currently lists every challenge
as unresolved.

### Profiling

`THINK_TANK_PROFILE=1` records a span for every graph node, LLM call, embedding
request and vector-store query, then prints exclusive time per kind plus the
slowest spans at exit. Each span is tagged with the run that produced it, so the
report covers only the run that just finished.

Output tokens dominate: latency tracks output length divided by provider
throughput (~200 tok/s), so prompt brevity is the main lever, not parallelism.
