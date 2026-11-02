# AGENTS.md

Guidance for coding agents working in this repository.

Think Tank is a multi-agent deliberation system: four agents debate a topic in rounds and an Arbiter decides when they have converged. It is a single Rust crate in `rust/`, written in 2021 edition and built with Cargo. There is no Python code left — the rewrite replaced it.

## Commands

```bash
cargo build --manifest-path rust/Cargo.toml          # make build
cargo run --release --manifest-path rust/Cargo.toml -- "topic..."   # make run
cargo test --manifest-path rust/Cargo.toml           # make test
make check                                           # fmt-check + clippy + test (what CI runs)
```

`make run TOPIC="..."` forwards the topic as one quoted argument (so `?`, `*` and multi-word text are not split or glob-expanded); with no `TOPIC` the CLI prompts for one. All commands run from the repo root; `rust/` is not a separate workspace.

## Architecture

### Graph and state

`rust/src/graph.rs` runs a strictly sequential loop: `researcher → skeptic → visionary → synthesizer → arbiter`, and `route_after_arbiter` either loops back to `researcher` or ends. The loop ends when the arbiter sets `state.synthesis`; it continues when it sets `state.expansion` (a directive the next round's agents read).

`ThinkTankState` (`rust/src/state.rs`) has **no reducers**. Every node clones the state, appends to the relevant vector, and returns the whole new state — appending only the new artefact would overwrite history.

`current_round` is 0-based and is incremented only by the arbiter. Agents filter artefacts by `round == current_round`; the arbiter treats `current_round + 1` as rounds completed.

`graph::run` calls the observer once with the initial state before any node runs, mirroring LangGraph's `stream_mode="values"`, then once per distinct `current_round`.

### Agents (`rust/src/agents/`)

Each agent module follows the same shape: the system prompt lives in `prompts.rs`, a `*_node_body` builds markdown context sections and calls the LLM, and a public `*_node` wrapper only adds a telemetry `span`. LLM output is parsed into an `*Output` struct and then hydrated into a domain model (`Claim`, `Challenge`, `LateralIdea`, `SynthesisAttempt`) from `rust/src/schemas.rs`.

- Only the **Researcher** emits `Claim`s and embeds them. It retrieves evidence once and caches it in `state.evidence` for later rounds.
- The **Arbiter** makes no LLM calls. Its score is `0.80 × semantic + 0.20 × (1 − opposition ratio)`, where semantic alignment compares this round's claim embeddings with prior rounds' (i.e. whether the position has stabilised). `Challenge.resolved` is never set anywhere, so the resolution rate is recorded on the span but deliberately not weighted. On convergence the final `Synthesis` reuses the Synthesizer's LLM-generated attempt for that round.
- Convergence config (`alignment_threshold`, `min_rounds`, `max_rounds`) comes from `state.config`; the defaults that actually apply live in `runner` (`DEFAULT_ALIGNMENT_THRESHOLD` etc., the arbiter's module constants are only a fallback).

`rust/src/agents/prompts.rs` is generated from the previous Python prompts and must stay byte-identical if you edit it; `tests/rules.rs` checks the dimension rendering that feeds the Skeptic prompt.

Prompts carry explicit word caps and a "Brevity" section on purpose: latency is dominated by output tokens. Keep new prompts equally terse.

### LLM providers (`rust/src/llm.rs`)

All providers speak the OpenAI protocol, so one HTTP client with a per-provider `base_url` covers them; the `PROVIDERS` table is the single place to add one. Rules that are easy to break:

- `openrouter` is **embeddings only** — `resolve_provider(name, for_chat: true)` returns an error for it. Default chat provider is `ollama_cloud`; default embeddings provider is `openrouter`.
- Chat and embedding providers resolve independently. Per-agent overrides follow config → `THINK_TANK_<AGENT>_*` env → global env → provider default. A global `THINK_TANK_CHAT_MODEL` is not applied to an agent whose provider was overridden.
- `reasoning_effort` is sent only to providers whose `Provider::reasoning_effort` is set (Mistral returns HTTP 400 for it).
- Agents call `invoke_structured`, which retries up to 3 times when a weak model returns an empty or unparseable tool call, instead of failing inside a node.
- Credentials come only from the process environment; nothing loads `.env`. `.env.example` documents the variables.
- `THINK_TANK_BASE_URL_<PROVIDER>` redirects one provider at a local stub server; the tests use it.

### Knowledge base (`rust/src/kb.rs`)

The store is one JSON collection file per embedding space under `THINK_TANK_KB_PATH` (default `./kb_store`). The collection name is derived from the embedding provider and model (`embedding_collection_name`), so switching embedding models uses a separate collection rather than mixing vector dimensions. It is seeded from `SEED_DOCUMENTS` (dummy remote-work facts) when empty, and retrieval is cosine top-k. The legacy `chroma_db/` directory belongs to the removed Python implementation and is not read.

### Entry point and shared setup

`rust/src/runner.rs` holds setup shared by the CLI and the tests: `initial_state`, `Config` and its convergence defaults, the credential check (`MissingCredentialsError`), and `prepare_run` (open and seed the collection). `rust/src/main.rs` is thin: it prints `rust/src/print.rs`'s rendering, which reproduces the old CLI's `textwrap` output.

### Telemetry (`rust/src/telemetry.rs`)

`span(name, kind, f)` is a no-op unless `THINK_TANK_PROFILE=1`. Spans nest and are tagged with the run id from `run_scope`. The CLI prints a per-kind exclusive-time report at exit. Wrap new LLM, embedding, or vector-store calls in a span.

## Tests

Tests make no network calls. `rust/tests/support/mod.rs` runs a local OpenAI-protocol stub server and installs fake credentials; `tests/gate1.rs` drives the real loop against it and asserts node ordering, whole-state extension, and the arbiter formula. `tests/parity.rs` replays `rust/fixtures/python_golden.json` (recorded from the deleted Python implementation) and requires identical serialization, scores and CLI rendering. `tests/rules.rs` pins the provider/model/credential rules and dimension coercion.

Env-mutating tests hold `support::lock()` for their whole body; the stub keeps its own separate mutex because its server thread needs it while a test runs.

`rust/fixtures/record_python_golden.py` is **historical provenance only** — it imports the deleted `think_tank` package and cannot run. Do not treat it as part of the build.

## Gotchas

- The arbiter's module constants (0.75/2/6) are fallbacks; `runner::DEFAULT_ALIGNMENT_THRESHOLD` (0.65/2/6) is what a run actually uses.
- `docs/` holds dated research notes, not current-state documentation.
