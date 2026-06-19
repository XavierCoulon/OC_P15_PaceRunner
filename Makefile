.DEFAULT_GOAL := help
.PHONY: help install run test lint format typecheck check clean

PORT ?= 8000

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Installe les dépendances (uv sync)
	uv sync

run: ## Lance l'API en local (rechargement auto) — PORT=8000 par défaut
	uv run uvicorn app.main:app --app-dir backend --reload --port $(PORT)

test: ## Lance les tests
	uv run pytest

lint: ## Lint (ruff)
	uv run ruff check

format: ## Formate le code (ruff)
	uv run ruff format

typecheck: ## Vérifie les types (mypy strict)
	uv run mypy

eval: ## Évalue le LLM vs baseline sur les cas types (nécessite Ollama)
	PYTHONPATH=backend uv run python -m app.evaluation

check: lint typecheck test ## Vérifie tout (lint + types + tests), comme la CI

clean: ## Supprime les caches Python/outils
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
