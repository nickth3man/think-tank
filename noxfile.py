"""Nox automation sessions for think-tank."""

import nox

nox.options.sessions = ["tests", "lint", "typecheck", "security"]
nox.options.default_venv_backend = "uv"


@nox.session(python="3.13")
def tests(session: nox.Session) -> None:
    """Run the test suite with coverage."""
    session.run("uv", "sync", "--group", "dev", external=True)
    session.run(
        "pytest",
        "--cov=think_tank",
        "--cov-report=term-missing",
        "--cov-report=html:htmlcov",
        *session.posargs,
        external=True,
    )


@nox.session(python="3.13")
def lint(session: nox.Session) -> None:
    """Lint and format-check with ruff."""
    session.run("uv", "sync", "--group", "dev", external=True)
    session.run("ruff", "check", ".", external=True)
    session.run("ruff", "format", "--check", ".", external=True)


@nox.session(python="3.13")
def fmt(session: nox.Session) -> None:
    """Auto-fix lint issues and reformat with ruff."""
    session.run("uv", "sync", "--group", "dev", external=True)
    session.run("ruff", "check", "--fix", ".", external=True)
    session.run("ruff", "format", ".", external=True)


@nox.session(python="3.13")
def typecheck(session: nox.Session) -> None:
    """Run pyright and ty type checkers."""
    session.run("uv", "sync", "--group", "dev", external=True)
    session.run("pyright", external=True)
    session.run("ty", "check", external=True)


@nox.session(python="3.13")
def security(session: nox.Session) -> None:
    """Security audit with bandit and dependency vulnerability check."""
    session.run("uv", "sync", "--group", "dev", external=True)
    session.run(
        "bandit",
        "-r",
        "think_tank",
        "main.py",
        "app.py",
        "-c",
        "pyproject.toml",
        external=True,
    )


@nox.session(python="3.13")
def deadcode(session: nox.Session) -> None:
    """Find dead/unreachable code with vulture."""
    session.run("uv", "sync", "--group", "dev", external=True)
    session.run("vulture", "think_tank", "main.py", "app.py", external=True)


@nox.session(python="3.13")
def mutation(session: nox.Session) -> None:
    """Run mutation tests with mutmut (slow — run manually)."""
    session.run("uv", "sync", "--group", "dev", external=True)
    session.run("mutmut", "run", external=True)
