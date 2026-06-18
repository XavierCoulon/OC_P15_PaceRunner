# PaceRunner — backend

Orchestrateur déterministe **FastAPI** (cf. [ADR-1](../docs/03-solution-technique.md)).
Le projet Python est **unique et géré à la racine** du dépôt ; `backend/` est un dossier de sources.

## Développement (depuis la racine)

```bash
uv sync                 # crée le .venv (racine) et installe les dépendances
uv run uvicorn app.main:app --reload --app-dir backend   # API sur http://127.0.0.1:8000
```

`GET /health` → `{"status": "ok"}`.

## Qualité (depuis la racine)

```bash
uv run ruff check       # lint
uv run ruff format      # formatage
uv run mypy             # typage strict
uv run pytest           # tests
```

Hooks `pre-commit` configurés à la racine (`.pre-commit-config.yaml`).
