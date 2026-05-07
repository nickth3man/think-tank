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
python main.py
```

## Project Structure

```
think_tank/
├── __init__.py
├── schemas.py      # Pydantic models (Claim, Challenge, Synthesis, …)
├── state.py        # LangGraph state definition
├── graph.py        # Graph topology construction
├── arbiter.py      # Arbiter node + routing logic
└── agents/
    ├── researcher.py
    ├── skeptic.py
    ├── visionary.py
    └── synthesizer.py
```
