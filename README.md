# Think Tank

Multi-agent deliberation system built with [LangGraph](https://github.com/langchain-ai/langgraph). Four specialised agents collaborate through structured rounds of debate, converging on a synthesised answer.

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
uv sync
python main.py          # CLI — prompts for a topic
python app.py           # FastAPI observability dashboard at http://localhost:7860
```

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
Each Chroma collection is namespaced per embedding space, so switching
embedding models never mixes incompatible vectors.

## Project Structure

```
think_tank/
├── schemas.py          # Pydantic models (Claim, Challenge, Synthesis, …)
├── state.py            # LangGraph state definition (ThinkTankState)
├── llm.py              # Provider registry + chat/embedding factories
├── kb.py               # Chroma collection + seed documents
├── graph.py            # Graph topology construction
├── runner.py           # Run setup shared by CLI + dashboard (config, seed, creds)
├── telemetry.py        # Span recording + profiling reports
├── agents/
│   ├── researcher.py   # Evidence-grounded claims via vector KB
│   ├── skeptic.py      # Structured challenge generation
│   ├── visionary.py    # Lateral idea proposals
│   ├── synthesizer.py  # Cross-agent synthesis attempts
│   └── arbiter.py      # Arbiter node + convergence logic
└── dashboard/
    ├── events.py       # LangGraph stream → dashboard event mapping
    └── server.py       # FastAPI app (routes, websocket streaming)
web/index.html          # Dashboard frontend (served by /)
tests/                  # Mirrors the package; conftest.py holds fixtures
main.py                 # CLI entry point
app.py                  # Dashboard entry point (thin alias for the FastAPI app)
```

## Development

### Install

```bash
uv sync --group dev
```

### Common commands

```bash
make test          # pytest + coverage report
make lint          # ruff check
make fmt           # ruff check --fix + ruff format
make typecheck     # pyright
make ty            # ty (Astral type checker)
make security      # bandit security scan
make deadcode      # vulture unused-code scan
make check         # all quality gates (no mutation)
make pre-commit    # run all pre-commit hooks
```

### Test automation (nox)

```bash
uv run nox             # all sessions
uv run nox -s tests    # tests only
uv run nox -s lint     # lint only
uv run nox -s typecheck
uv run nox -s security
uv run nox -s mutation  # mutation tests (slow)
```

### Pre-commit hooks

```bash
make pre-commit-install   # wire hooks into .git/hooks (once)
```

Hooks run on every commit: ruff lint+format, bandit, pyright, and standard file hygiene.

## Tooling

| Tool | Purpose |
|------|---------|
| [uv](https://github.com/astral-sh/uv) | Package manager and virtual env |
| [ruff](https://github.com/astral-sh/ruff) | Linter + formatter (replaces flake8, black, isort) |
| [pyright](https://github.com/microsoft/pyright) | Static type checker |
| [ty](https://github.com/astral-sh/ty) | Fast type checker (Astral) |
| [pytest](https://pytest.org) | Test runner |
| [hypothesis](https://hypothesis.works) | Property-based testing |
| [pytest-cov](https://pytest-cov.readthedocs.io) | Coverage reporting |
| [freezegun](https://github.com/spulec/freezegun) | Time travel for tests |
| [dirty-equals](https://dirty-equals.helpmanual.io) | Declarative test assertions |
| [syrupy](https://github.com/syrupy-project/syrupy) | Snapshot testing |
| [bandit](https://bandit.readthedocs.io) | Security linter |
| [vulture](https://github.com/jendrikseipp/vulture) | Dead code detection |
| [mutmut](https://mutmut.readthedocs.io) | Mutation testing |
| [nox](https://nox.thea.codes) | Test automation across sessions |

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
| `THINK_TANK_PROFILE` | unset | `1` prints a per-stage latency profile at exit and serves it on `/profile` |
| `CHROMA_DB_PATH` | `./chroma_db` | Vector store path |

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
slowest spans. Every span is tagged with the run that produced it, so
`GET /profile?run_id=<id>` separates concurrent websocket clients; `main.py`
scopes its own report to the run it just executed. Output tokens dominate: latency tracks output length divided by
provider throughput (~200 tok/s), so prompt brevity is the main lever, not
parallelism.
