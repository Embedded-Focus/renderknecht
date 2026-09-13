RUNTIME ?= podman
GIT_HASH ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)

.PHONY: help test lint format check-format type-check check audit pre-commit

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}'

.PHONY: build
build: ## Build container image
	$(RUNTIME) build \
		--build-arg GIT_HASH=$(GIT_HASH) \
		--build-arg RENDERKNECHT_VERSION=$$(uv version --short) \
		-t renderknecht:latest \
		-f Dockerfile.renderknecht .

test: ## Run tests
	uv run --extra container pytest

lint: ## Run Ruff lint checks
	uv run ruff check

format: ## Format Python files with Ruff
	uv run ruff format

check-format: ## Check Python formatting with Ruff
	uv run ruff format --check

type-check: ## Run type checks
	uv run ty check

check: check-format lint type-check test ## Run all checks

audit: ## Audit locked Python dependencies
	uv audit --locked

pre-commit: ## Run pre-commit hooks on all tracked files
	uv run pre-commit run --all-files
