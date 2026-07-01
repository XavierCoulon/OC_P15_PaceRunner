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

front: ## Lance le front Streamlit (port 7860)
	PYTHONPATH=backend uv run streamlit run front/Home.py --server.port 7860

dev: ## Lance la stack : Ollama (llama3.1:8b) si éteint + backend (:8000) + front (:7860)
	@curl -s http://localhost:11434/api/version >/dev/null 2>&1 || \
		{ echo "→ Ollama éteint : démarrage en arrière-plan"; nohup ollama serve >/tmp/ollama-pacerunner.log 2>&1 & sleep 2; }
	@export LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=llama3.1:8b LLM_API_KEY=; \
	trap 'kill 0' EXIT INT TERM; \
	uv run uvicorn app.main:app --app-dir backend --port $(PORT) & \
	PYTHONPATH=backend uv run streamlit run front/Home.py --server.port 7860 --server.headless true & \
	wait

test: ## Lance les tests
	uv run pytest

lint: ## Lint + vérif format (comme la CI)
	uv run ruff check
	uv run ruff format --check

format: ## Formate le code (ruff)
	uv run ruff format

typecheck: ## Vérifie les types (mypy strict)
	uv run mypy

eval: ## Évalue le LLM vs baseline sur les cas types (nécessite Ollama)
	PYTHONPATH=backend uv run python -m app.evaluation

db-ping: ## Vérifie la connexion à la base (DATABASE_URL)
	PYTHONPATH=backend uv run python -m app.db

migration: ## Génère une migration Alembic — usage : make migration m="message"
	uv run alembic revision --autogenerate -m "$(m)"

migrate: ## Applique les migrations (upgrade head)
	uv run alembic upgrade head

check: lint typecheck test ## Vérifie tout (lint + types + tests), comme la CI

clean: ## Supprime les caches Python/outils
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
