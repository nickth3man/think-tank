# Think Tank

Multi-agent deliberation system written in Rust. Four specialised agents collaborate through structured rounds of debate, converging on a synthesised answer.

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

## Quick Start

```bash
cargo build --release --manifest-path rust/Cargo.toml
cargo run --release --manifest-path rust/Cargo.toml -- "Should companies adopt fully remote work?"
```

`make run` is the same thing. With no topic argument the CLI prompts for one.

## Prerequisites

Credentials come from your shell environment — the app does not read `.env`.
`.env.example` lists every supported variable; append the block you need to
`~/.zshenv` and open a new shell:

```bash
cat .env.example >> ~/.zshenv   # then uncomment the keys you have
```

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
embeddings and judge/decision models. Requesting it for agent chat raises an
error instead of silently routing there.

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
make build         # cargo build
make test          # cargo test (stub-server integration + golden parity)
make fmt           # rustfmt
make fmt-check     # formatting check
make lint          # clippy, warnings denied
make check         # fmt-check + clippy + test — what CI runs
make run           # release build, then run the CLI
```

Tests never touch the network. A local stub server speaks the OpenAI protocol,
so the loop, the arbiter formula and the golden-fixture replay all run
deterministically without credentials.

`rust/fixtures/python_golden.json` was recorded from the Python implementation
this crate replaced. Replaying it is what pins behavioural parity; the recorder
script beside it is kept for provenance only and cannot run.

## Tooling

| Tool | Purpose |
|------|---------|
| [Cargo](https://doc.rust-lang.org/cargo/) | Build and test runner |
| [rustfmt](https://github.com/rust-lang/rustfmt) | Formatter |
| [clippy](https://github.com/rust-lang/rust-clippy) | Lints (denied in CI) |
| [serde](https://serde.rs) | Serialization, including Python-compatible timestamps |
| [ureq](https://github.com/algesten/ureq) | Blocking HTTP client for the OpenAI protocol |

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

Convergence parameters are passed at runtime in the state `config` dict:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `alignment_threshold` | `0.65` | Minimum score to declare convergence |
| `min_rounds` | `2` | Minimum deliberation rounds |
| `max_rounds` | `6` | Hard ceiling — forces synthesis |

The alignment score is `0.80 × semantic + 0.20 × (1 − opposition ratio)`.
Semantic alignment compares this round's claim against the previous round's, so
it measures whether the position has stabilised. `Challenge.resolved` is never
set by any producer in this codebase, so the resolution rate is recorded on the
`arbiter.score` span but is not weighted — including it capped the score at a
constant `0.75` and made every run converge on the same number. Consequently
`Synthesis.unresolved_challenges` currently lists every challenge as unresolved.

### Profiling

`THINK_TANK_PROFILE=1` records a span for every graph node, LLM call, embedding
request and vector-store query, then prints exclusive time per kind plus the
slowest spans. Every span is tagged with the run that produced it, so the CLI scopes its own report to the run it just executed. Output tokens dominate: latency tracks output length divided by
provider throughput (~200 tok/s), so prompt brevity is the main lever, not
parallelism.
