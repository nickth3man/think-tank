# AGENTS.md

Guidance for coding agents working in this repository.

Think Tank is a LangGraph multi-agent deliberation system: four LLM agents debate a topic in rounds and an Arbiter decides when they have converged. Python 3.13, managed with `uv`. It is an unpackaged flat layout — run everything from the repo root.

## Commands

```bash
uv sync --group dev                 # install (make install)
uv run python main.py "topic..."    # CLI run; prompts for a topic if none given (make run)
uv run python app.py                # FastAPI dashboard on :7860 (make app; PORT overrides)
uv run uvicorn app:app --reload --port 7860
```

Tests and quality gates (CI runs lint, format check, pyright, ty, bandit and pytest on pushes/PRs to `main`/`dev`):

```bash
make test                           # pytest with coverage (fails under 40%)
make test-fast                      # pytest --no-cov -x
uv run pytest tests/test_arbiter.py::TestPairwiseAlignment --no-cov   # single test
uv run pytest -k "alignment" --no-cov
make lint / make fmt / make fmt-check   # ruff (line length 100, mccabe max 12)
make typecheck                      # pyright (standard mode, think_tank + main.py + app.py)
make ty                             # Astral ty — CI runs both type checkers
make security                       # bandit
make check                          # lint + fmt-check + pyright + ty + bandit
```

`pytest` addopts always include coverage and HTML output; pass `--no-cov` for quick iteration.

## Architecture

### Graph and state

`think_tank/graph.py` builds a strictly sequential loop: `researcher → skeptic → visionary → synthesizer → arbiter`, and `route_after_arbiter` either loops back to `researcher` or ends. The loop ends when the arbiter sets `state["synthesis"]`; it continues when it sets `state["expansion"]` (a directive the next round's agents read).

`ThinkTankState` (`think_tank/state.py`) is a plain `TypedDict` with **no reducers**. Every node returns a partial update and must return the *whole* list it extends (`{"claims": [*existing_claims, claim]}`), not just the new item — returning only the new item would overwrite history.

`current_round` is 0-based and is incremented only by the arbiter. Agents filter artifacts by `round == current_round`; the arbiter treats `current_round + 1` as rounds completed.

### Agents (`think_tank/agents/`)

Each agent module follows the same shape: a `*_SYSTEM_PROMPT` constant, a `_<agent>_node_body(state)` that builds markdown context sections and calls the LLM, and a public `<agent>_node` wrapper that only adds a telemetry `span`. LLM output is parsed into a `*Output` schema and then hydrated into a domain model (`Claim`, `Challenge`, `LateralIdea`, `SynthesisAttempt`) from `think_tank/schemas.py`.

- Only the **Researcher** emits `Claim`s and embeds them. It retrieves evidence from Chroma once and caches it in `state["evidence"]` for later rounds.
- The **Arbiter** makes no LLM calls. Its score is `0.80 × semantic + 0.20 × (1 − opposition ratio)`, where semantic alignment compares this round's claim embeddings with prior rounds' (i.e. whether the position has stabilised). `Challenge.resolved` is never set anywhere, so the resolution rate is recorded on the span but deliberately not weighted. On convergence the final `Synthesis` reuses the Synthesizer's LLM-generated attempt for that round.
- Convergence config (`alignment_threshold`, `min_rounds`, `max_rounds`) comes from `state["config"]`; the defaults that actually apply live in `runner.DEFAULT_CONFIG` (the arbiter's module constants are only a fallback).

Prompts carry explicit word caps and a "Brevity" section on purpose: latency is dominated by output tokens. Keep new prompts equally terse.

### LLM providers (`think_tank/llm.py`)

All providers speak the OpenAI protocol, so one `ChatOpenAI`/`OpenAIEmbeddings` client with a per-provider `base_url` covers them; the `PROVIDERS` registry is the single place to add one. Rules that are easy to break:

- `openrouter` is **embeddings/judge only** — `resolve_provider(..., for_chat=True)` raises for it. Default chat provider is `ollama_cloud`; default embeddings provider is `openrouter`.
- Chat and embedding providers resolve independently. Per-agent overrides follow config → `THINK_TANK_<AGENT>_*` env → global env → provider default. A global `THINK_TANK_CHAT_MODEL` is not applied to an agent whose provider was overridden.
- `reasoning_effort` is sent only to providers whose `Provider.reasoning_effort` is set (Mistral returns HTTP 400 for it).
- Agents should call `agent_structured_llm(agent, config, Schema)`, which retries up to 3 times when a weak model returns an empty or unparseable tool call, instead of raising inside a node.
- Credentials come only from the process environment; nothing loads `.env`. `.env.example` documents the variables.

### Knowledge base (`think_tank/kb.py`)

Chroma persisted at `CHROMA_DB_PATH` (default `./chroma_db`). The collection name is derived from the embedding provider and model (`embedding_collection_name`), so switching embedding models uses a separate collection rather than mixing vector dimensions. It is seeded from `SEED_DOCUMENTS` (dummy remote-work facts) when empty.

### Entry points and shared setup

`think_tank/runner.py` holds setup shared by both entry points: `initial_state()`, `DEFAULT_CONFIG`, the credential check (`MissingCredentialsError`), and `prepare_run()` (open and seed the vector store). Put run setup here, not in `main.py`/`app.py`, which are thin and excluded from coverage.

- `main.py` streams with `graph.stream(stream_mode="values")` and prints state per round.
- `app.py` re-exports `think_tank.dashboard.server:app`. The `/observe` websocket streams `graph.astream(stream_mode="updates")`; `dashboard/events.py`'s `StreamAdapter` diffs state deltas into frontend events. The frontend is a single static file, `web/index.html`, loaded at import time; `/?demo=1` plays a built-in trace without credentials.

### Telemetry (`think_tank/telemetry.py`)

`span(name, kind, **attrs)` is a no-op unless `THINK_TANK_PROFILE=1`. Spans nest and are tagged with the run id from `run_scope()` (a `ContextVar`, so concurrent websocket runs stay separate). `GET /profile?run_id=...` and the CLI report use exclusive time per kind. Wrap new LLM, embedding, or vector-store calls in a span.

## Tests

Tests make no network calls. `tests/test_llm.py` scrubs `THINK_TANK_*` and provider-key env vars with an autouse fixture and sets fake keys; other tests monkeypatch module-level functions (`kb.get_vector_store`, `researcher.retrieve`, `runner.missing_credentials`). `tests/conftest.py` provides the `make_claim` / `make_challenge` builders and aligned/diverged claim fixtures.

## Gotchas

- The Makefile's `app` target description still says "Gradio"; the dashboard is FastAPI.
- `docs/` holds dated research notes (repo layout, Jev judge-model integration), not current-state documentation.
