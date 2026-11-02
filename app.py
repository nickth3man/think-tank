"""app.py — Entry point for the Think Tank observability dashboard.

The FastAPI app lives in :mod:`think_tank.dashboard.server`; the frontend is
``web/index.html``. This module only exists so both invocations work from the
repo root:

    python app.py
    uv run uvicorn app:app --reload --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import os

from think_tank.dashboard.server import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))  # nosec B104
