.DEFAULT_GOAL := help
.PHONY: help install sync test test-fast lint fmt typecheck ty security deadcode \
        pre-commit-install pre-commit mutation nox-all clean

UV := uv run

# ─── Setup ───────────────────────────────────────────────────────────────────

install: ## Install all dependencies including dev group
	uv sync --group dev

sync: install ## Alias for install

pre-commit-install: ## Install pre-commit hooks into .git/hooks
	$(UV) pre-commit install

# ─── Testing ─────────────────────────────────────────────────────────────────

test: ## Run full test suite with coverage
	$(UV) pytest

test-fast: ## Run tests without coverage (faster feedback)
	$(UV) pytest --no-cov -x

test-watch: ## Re-run tests on file changes (requires pytest-watch)
	$(UV) ptw -- --no-cov

mutation: ## Run mutation tests with mutmut (slow)
	$(UV) mutmut run

# ─── Linting & Formatting ────────────────────────────────────────────────────

lint: ## Check for lint errors with ruff
	$(UV) ruff check .

fmt: ## Auto-fix lint issues and reformat code
	$(UV) ruff check --fix .
	$(UV) ruff format .

fmt-check: ## Check formatting without making changes
	$(UV) ruff format --check .

# ─── Type Checking ───────────────────────────────────────────────────────────

typecheck: ## Run pyright type checker
	$(UV) pyright

ty: ## Run ty type checker (Astral)
	$(UV) ty check

# ─── Security & Analysis ─────────────────────────────────────────────────────

security: ## Run bandit security scan
	$(UV) bandit -r think_tank main.py app.py -c pyproject.toml

deadcode: ## Find unused code with vulture
	$(UV) vulture think_tank main.py app.py

# ─── Pre-commit ───────────────────────────────────────────────────────────────

pre-commit: ## Run all pre-commit hooks against all files
	$(UV) pre-commit run --all-files

# ─── Nox (multi-session automation) ─────────────────────────────────────────

nox-all: ## Run all nox sessions
	$(UV) nox

nox-tests: ## Run nox tests session only
	$(UV) nox -s tests

nox-lint: ## Run nox lint session only
	$(UV) nox -s lint

# ─── All quality gates ───────────────────────────────────────────────────────

check: lint fmt-check typecheck ty security ## Run all quality checks (no mutation)

# ─── Run ─────────────────────────────────────────────────────────────────────

run: ## Run CLI deliberation (prompts for topic)
	$(UV) python main.py

app: ## Launch Gradio web UI
	$(UV) python app.py

# ─── Cleanup ─────────────────────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	rm -rf htmlcov .coverage coverage.xml .pytest_cache .ruff_cache .mutmut-cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ─── Help ────────────────────────────────────────────────────────────────────

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
