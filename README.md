# PaceRunner 🏃

**Stratégies de course à pied prédictives** : à partir d'un fichier **GPX** et d'une date de course,
l'app génère une **allure conseillée km par km**, personnalisée selon la **forme du coureur** (COROS) et
la **météo du jour J**.

Projet technique du portfolio **P15 — AI Engineer** (formation IA). Pensé « comme en entreprise » et
positionné sur la **mise en production** : orchestrateur déterministe, LLM cadré par des garde-fous,
journalisation des prédictions et **monitoring du modèle**.

---

## Ce que fait l'app

1. **Upload d'un GPX** + date/heure de course.
2. **Pipeline d'orchestration** (FastAPI) :
   - parsing du tracé + **nettoyage des altitudes** (Open Topo Data),
   - **forme athlète** (COROS : allure seuil, VO2max, récupération, poids),
   - **météo jour J** (Open-Meteo : prévision ≤16 j, sinon **relevés de l'an dernier** + historique 3 ans, ERA5),
   - **baseline déterministe** (grade-adjusted pace, modèle de Minetti),
   - **génération LLM** (Llama 3.1 8B) *ancrée sur la baseline*, validée en JSON strict (Pydantic).
3. **Garde-fous métier** : si la sortie LLM est aberrante ou indisponible → **repli sur la baseline**
   (l'utilisateur a toujours une stratégie réaliste). L'origine (IA / repli) est affichée.
4. **Restitution** (Streamlit) : carte du tracé, profil de dénivelé, courbe d'allure, tableau km/km
   (export CSV), conditions météo à icônes.
5. **Journalisation** de chaque run (Neon Postgres) → pages **Historique** et **Monitoring** (KPIs).

```
GPX + date ─▶ FastAPI (orchestrateur déterministe)
               ├─ parsing & nettoyage altitudes (Open Topo Data)
               ├─ forme athlète (COROS via client MCP httpx maison)
               ├─ météo + qualité air jour J (Open-Meteo)
               ├─ baseline déterministe (grade-adjusted, fallback + référence)
               └─ LLM Llama 3.1 8B (Ollama local OU HF Inference)
                    └─ garde-fous + validation Pydantic → PaceStrategy
                         └─ journalisée (Neon Postgres)
Front Streamlit ─▶ génération · historique · monitoring
```

## Stack

Python · **FastAPI** · Pydantic / pydantic-settings · **Streamlit** (pydeck, Altair) ·
**SQLModel / Neon Postgres** + Alembic · client **MCP COROS** maison (httpx) ·
LLM **OpenAI-compatible** (Ollama local ou HF Inference) · `uv` · ruff · mypy (strict) · GitHub Actions.

## Architecture

Clean Architecture (ports/adapters), orchestrateur **déterministe** : le LLM ne produit que le JSON
de stratégie à partir de données déjà nettoyées (cf. [ADR-1](docs/03-solution-technique.md)).

```
backend/app/
  api/        routes + sécurité (Bearer)
  domain/     modèles Pydantic + ports (Protocols)
  adapters/   GPX, Open Topo Data, COROS, Open-Meteo, LLM, repository
  services/   orchestrateur, baseline, garde-fous, métriques qualité
  db/         moteur async, modèles, migrations Alembic
front/        app Streamlit (Génération / Historique / Monitoring)
docs/         livrables d'évaluation (C1 besoins · C2 audit data · C3 solution technique)
```

## Démarrage local

Prérequis : [`uv`](https://docs.astral.sh/uv/), et selon le moteur LLM choisi
[Ollama](https://ollama.com) (local) **ou** un token Hugging Face.

```bash
uv sync                 # installe les dépendances
cp .env.example .env    # puis renseigner les secrets (API_TOKEN, COROS, DATABASE_URL…)
```

Lancer toute la stack (backend `:8000` + front `:7860`) :

```bash
make dev      # Ollama (llama3.1:8b, démarré auto) + backend + front
```

Le front est sur **http://localhost:7860**. « Générer » utilise **DeepSeek** via HF Inference
(nécessite `HF_TOKEN` dans `.env`) ; « Comparer » ajoute **llama3.1:8b** en local (Ollama).

### Commandes utiles (`make help`)

| Commande | Rôle |
|---|---|
| `make dev` | Stack complète (Ollama + backend + front) |
| `make run` / `make front` | Backend seul / front seul |
| `make check` | lint + types + tests (comme la CI) |
| `make eval` | Évalue le LLM vs baseline sur des parcours types |
| `make migrate` | Applique les migrations Alembic (Neon) |

## Choisir le moteur LLM (local ou HF)

Un **adapter OpenAI-compatible unique** : on bascule par 3 variables (`LLM_BASE_URL`, `LLM_MODEL`,
`LLM_API_KEY`), sans changer le code.

- **Local — Ollama** : `LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=llama3.1:8b`.
- **HF Inference** : `LLM_BASE_URL=https://router.huggingface.co/v1`,
  `LLM_MODEL=meta-llama/Llama-3.1-8B-Instruct`, `LLM_API_KEY=<token HF>`
  (token *fine-grained* avec la permission *Inference Providers*).

## Qualité

- **~106 tests** (pytest, respx pour mocker l'HTTP), **mypy strict**, **ruff** (lint + format).
- **CI GitHub Actions** : lint + types + tests à chaque push/PR ; hooks `pre-commit` à la racine
  (`.pre-commit-config.yaml`). Le projet Python est **unique, géré à la racine** ; `backend/` et
  `front/` sont des dossiers de sources.
- **Garde-fous + fallback** : aucune réponse aberrante servie ; dégradation gracieuse si une source KO.
- **Monitoring** : métriques qualité journalisées (latence, % IA vs repli, % garde-fous respectés,
  écart à la baseline) et exposées via `/stats` + page Monitoring.

## API (extrait)

`GET /health` · `POST /strategy` (GPX → stratégie + contexte) · `POST /profile` · `GET /weather` ·
`GET /athlete` · `GET /history` · `GET /history/{id}` · `GET /stats` — endpoints protégés par token Bearer.

## Suivi de projet & livrables

- Livrables d'évaluation (conduite de projet) dans [`docs/`](docs/) : besoins (C1), audit data (C2),
  solution technique & ADR (C3).
- Board : [GitHub Projects](https://github.com/users/XavierCoulon/projects/6).
