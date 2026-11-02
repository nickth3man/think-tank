.DEFAULT_GOAL := help
.PHONY: help build run fmt fmt-check lint test check clean

CARGO := cargo
RUST_DIR := rust

# Topic forwarded to the CLI. Quoted so a multi-word topic stays one argument
# and `?`/`*` are not glob-expanded; empty means "prompt for one".
TOPIC_ARG := $(if $(strip $(TOPIC)),"$(strip $(TOPIC))",)

# ─── Setup ───────────────────────────────────────────────────────────────────

build: ## Compile the crate (debug)
	$(CARGO) build --manifest-path $(RUST_DIR)/Cargo.toml

release: ## Compile the crate (release, used for real runs)
	$(CARGO) build --release --manifest-path $(RUST_DIR)/Cargo.toml

# ─── Testing ─────────────────────────────────────────────────────────────────

test: ## Run the full test suite (stub-server integration + golden parity)
	$(CARGO) test --manifest-path $(RUST_DIR)/Cargo.toml

test-fast: ## Run the integration tests only (skips doc tests)
	$(CARGO) test --manifest-path $(RUST_DIR)/Cargo.toml --tests

# ─── Linting & Formatting ────────────────────────────────────────────────────

fmt: ## Apply rustfmt
	$(CARGO) fmt --manifest-path $(RUST_DIR)/Cargo.toml

fmt-check: ## Check formatting without making changes
	$(CARGO) fmt --manifest-path $(RUST_DIR)/Cargo.toml --check

lint: ## Run clippy, warnings denied
	$(CARGO) clippy --manifest-path $(RUST_DIR)/Cargo.toml --all-targets -- -D warnings

# ─── All quality gates ───────────────────────────────────────────────────────

check: fmt-check lint test ## Formatting, lints and tests (what CI runs)

# ─── Run ─────────────────────────────────────────────────────────────────────

run: ## Run CLI deliberation: make run TOPIC="..." (prompts when TOPIC is empty)
	$(CARGO) run --release --manifest-path $(RUST_DIR)/Cargo.toml -- $(TOPIC_ARG)

# ─── Cleanup ─────────────────────────────────────────────────────────────────

clean: ## Remove build artifacts and the local knowledge base
	$(CARGO) clean --manifest-path $(RUST_DIR)/Cargo.toml
	rm -rf kb_store

# ─── Help ────────────────────────────────────────────────────────────────────

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
