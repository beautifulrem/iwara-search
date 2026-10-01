.DEFAULT_GOAL := help
.PHONY: help install fmt lint typecheck jscheck test cov perf e2e check serve sync migrate docker

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies and git hooks
	uv sync
	uv run pre-commit install

fmt: ## Format code
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Lint (ruff)
	uv run ruff format --check .
	uv run ruff check .

typecheck: ## Static types (mypy --strict)
	uv run mypy

jscheck: ## Type-check the browser scripts (tsc --checkJs, needs Node)
	npx --yes --package typescript@5.9 tsc -p jsconfig.json

test: ## Fast test suite
	uv run pytest -m "not slow and not e2e" -n auto

cov: ## Tests with coverage gate
	uv run pytest -m "not slow and not e2e" -n auto --cov

perf: ## Performance budgets on a 200k-movie synthetic database
	uv run pytest -m slow

e2e: ## Browser end-to-end + axe accessibility tests
	uv sync --group e2e
	uv run playwright install chromium
	uv run pytest -m e2e

check: lint typecheck jscheck cov ## Everything CI runs except perf/e2e

serve: ## Development server with auto-reload
	uv run search-iwara serve --reload --port 8765

sync: ## Incremental sync
	uv run search-iwara sync latest

migrate: ## Create/upgrade the database schema
	uv run search-iwara db migrate

docker: ## Build the container image
	docker build -t search-iwara .
