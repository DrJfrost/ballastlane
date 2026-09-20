# Convenience wrapper. Every target maps to one command a reviewer could run
# by hand; nothing here is required to build or run the project.
.DEFAULT_GOAL := help
.PHONY: help install up down logs seed migrate revision test test-unit test-cov \
        lint format typecheck check api worker beat web build clean

BACKEND := backend
FRONTEND := frontend
PY := cd $(BACKEND) && uv run

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------- environment
install: ## Install backend and frontend dependencies
	cd $(BACKEND) && uv venv --python 3.12 && uv pip install -e ".[dev]"
	cd $(FRONTEND) && npm install
	cd $(BACKEND) && cp -n .env.example .env || true

# -------------------------------------------------------------------- docker
up: ## Build and start the whole stack (API, worker, beat, db, redis, web)
	docker compose up --build -d
	@echo "app   -> http://localhost:8080"
	@echo "docs  -> http://localhost:8000/docs"

down: ## Stop the stack and delete its volumes
	docker compose down -v

logs: ## Follow the logs of every service
	docker compose logs -f

# ----------------------------------------------------------------- local run
api: ## Run the API with autoreload
	$(PY) uvicorn taskflow.main:app --reload --port 8000

worker: ## Run a Celery worker
	$(PY) celery -A taskflow.infrastructure.tasks.celery_app:celery_app worker -l info

beat: ## Run the Celery scheduler
	$(PY) celery -A taskflow.infrastructure.tasks.celery_app:celery_app beat -l info

web: ## Run the Vite dev server
	cd $(FRONTEND) && npm run dev

# ------------------------------------------------------------------ database
migrate: ## Apply migrations
	$(PY) alembic upgrade head

revision: ## Autogenerate a migration: make revision m="add a column"
	$(PY) alembic revision --autogenerate -m "$(m)"

seed: ## Reset the demo data
	$(PY) python -m taskflow.scripts.seed

# --------------------------------------------------------------------- tests
test: ## Backend and frontend test suites
	$(PY) pytest
	cd $(FRONTEND) && npm test

test-unit: ## Backend unit tests only (no I/O)
	$(PY) pytest -m unit

test-cov: ## Backend tests with an HTML coverage report
	$(PY) pytest --cov-report=html
	@echo "report -> backend/htmlcov/index.html"

# --------------------------------------------------------------------- style
lint: ## Lint both sides
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check .
	cd $(FRONTEND) && npm run lint

format: ## Autoformat both sides
	cd $(BACKEND) && uv run ruff check --fix . && uv run ruff format .
	cd $(FRONTEND) && npx prettier --write "src/**/*.{ts,tsx,css}"

typecheck: ## Static types on both sides
	$(PY) mypy
	cd $(FRONTEND) && npm run typecheck

check: lint typecheck test ## Everything CI runs

clean: ## Remove caches and build output
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache \
	       $(BACKEND)/htmlcov $(BACKEND)/coverage.xml $(FRONTEND)/dist
