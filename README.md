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
python app.py           # Gradio web UI at http://localhost:7860
```

## Prerequisites

Copy `.env.example` to `.env` and set your OpenRouter API key:

```bash
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY=sk-or-v1-...
```

## Project Structure

```
think_tank/
├── schemas.py          # Pydantic models (Claim, Challenge, Synthesis, …)
├── state.py            # LangGraph state definition (ThinkTankState)
├── graph.py            # Graph topology construction
├── arbiter.py          # Arbiter node + convergence logic
└── agents/
    ├── researcher.py   # Evidence-grounded claims via vector KB
    ├── skeptic.py      # Structured challenge generation
    ├── visionary.py    # Lateral idea proposals
    └── synthesizer.py  # Cross-agent synthesis attempts
tests/
├── conftest.py         # Shared fixtures and factories
├── test_schemas.py     # Pydantic model validation (hypothesis + freezegun)
└── test_arbiter.py     # Alignment math unit tests
main.py                 # CLI entry point
app.py                  # Gradio UI entry point
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
| `OPENROUTER_API_KEY` | — | **Required.** OpenRouter API key |
| `DEFAULT_CHAT_MODEL` | `openai/gpt-4o-mini` | LLM for all agents |
| `OPENROUTER_EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Embeddings model |
| `CHROMA_DB_PATH` | `./chroma_db` | Vector store path |

Convergence parameters are passed at runtime in the state `config` dict:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `alignment_threshold` | `0.75` | Minimum score to declare convergence |
| `min_rounds` | `2` | Minimum deliberation rounds |
| `max_rounds` | `6` | Hard ceiling — forces synthesis |
