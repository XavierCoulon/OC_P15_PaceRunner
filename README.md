# PaceRunner 🏃

**Stratégies de course à pied prédictives** : à partir d'un fichier **GPX** et d'une date de course,
l'app génère une **allure conseillée km par km**, personnalisée selon la **forme du coureur** (COROS) et
la **météo du jour J**.

Projet technique du portfolio **P15 — AI Engineer** (formation IA). Pensé « comme en entreprise » et
positionné sur la **mise en production** : orchestrateur déterministe, LLM cadré par des garde-fous,
journalisation des prédictions et **monitoring du modèle**.

---

## Ce que fait l'app

0. **Prérequis — calibration personnalisée** (page *Données COROS*) : ingestion de l'**historique
   de courses COROS** (`querySportRecords`, batch puis incrémental) + jointure de la **météo
   historique** (ERA5). On en dérive un **profil de calibration** persisté : allures de référence
   par distance (meilleurs efforts réels), **sensibilité chaleur**, tendance de forme (ACWR).
1. **Upload d'un GPX** + date/heure, puis deux actions :
   - **« Générer »** → la stratégie de production.
   - **« Comparer »** → un banc d'essai entre moteurs (#74).
2. **Pipeline d'orchestration** (FastAPI), pour « Générer » :
   - parsing du tracé + **nettoyage des altitudes** (Open Topo Data),
   - **forme athlète du jour** (COROS : allure seuil, VO2max, récupération, poids),
   - **météo jour J** (Open-Meteo : prévision ≤16 j, sinon **relevés de l'an dernier** + historique 3 ans, ERA5),
   - **baseline déterministe calibrée** (grade-adjusted pace Minetti + facteurs de distance et
     sensibilité chaleur **personnalisés**),
   - **LLM DeepSeek-V3 ancré sur la baseline** : tactique bornée à ±20 % (negative split, gestion de
     l'effort) + **narratif de course par tranche**, validé en JSON strict (Pydantic).
3. **Garde-fous métier** : si la sortie LLM est aberrante ou indisponible → **repli sur la baseline**.
   L'origine (IA / repli) est affichée.
4. **Restitution** (Streamlit) : carte, profil de dénivelé, forme + météo affichées avant l'attente,
   stratégie recommandée + **plan par tranche** + tableau allure/km. Résultat **mémorisé** (persiste
   entre les pages).
5. **Journalisation** des générations de production (Neon Postgres) → pages **Historique** et
   **Monitoring** (volume, % IA vs repli, % personnalisées, écart baseline, latence).

```
Historique COROS ─▶ calibration (allures distance · chaleur · forme) ─▶ Neon
GPX + date ─▶ FastAPI (orchestrateur déterministe)
               ├─ parsing & nettoyage altitudes (Open Topo Data)
               ├─ forme athlète du jour (COROS via client MCP httpx maison)
               ├─ météo + qualité air jour J (Open-Meteo)
               ├─ baseline déterministe CALIBRÉE (grade-adjusted, fallback + référence)
               └─ « Générer » : DeepSeek-V3 ancré (tactique ±20 % + narratif)
                    └─ garde-fous + validation Pydantic → PaceStrategy → Neon
               └─ « Comparer » (#74) : baseline vs llama3.1:8b autonome vs DeepSeek CoT (brut)
Front Streamlit ─▶ Données COROS · génération · historique · monitoring
```

## Stack

Python · **FastAPI** · Pydantic / pydantic-settings · **Streamlit** (pydeck, Altair) ·
**SQLModel / Neon Postgres** + Alembic · client **MCP COROS** maison (httpx) ·
LLM **OpenAI-compatible** : **DeepSeek-V3** (HF Inference, production) + **llama3.1:8b** (Ollama,
banc d'essai) · `uv` · ruff · mypy (strict) · GitHub Actions.

## Architecture

Clean Architecture (ports/adapters), orchestrateur **déterministe** : le LLM ne produit que le JSON
de stratégie à partir de données déjà nettoyées (cf. [ADR-1](docs/03-solution-technique.md)).

```
backend/app/
  api/        routes + sécurité (Bearer)
  domain/     modèles Pydantic + ports (Protocols)
  adapters/   GPX, Open Topo Data, COROS (forme + historique), Open-Meteo, LLM, repository
  services/   orchestrateur, baseline calibrée, calibration, garde-fous, métriques qualité
  db/         moteur async, modèles, calibration store, migrations Alembic
front/        app Streamlit (Données COROS / Génération / Historique / Monitoring)
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

> **Deux usages distincts :**
> - **« Générer »** = stratégie de production. DeepSeek est **ancré sur la baseline** déterministe
>   (tactique bornée à ±20 %) avec **garde-fous + repli baseline**. C'est la stratégie fiable.
> - **« Comparer »** = banc d'essai (#74). llama3.1:8b et DeepSeek conçoivent **en mode autonome
>   brut : sans la baseline, sans garde-fou, sans repli**. C'est volontaire — ça sert à mesurer ce
>   que vaut un LLM seul. Conséquence : sur terrain raide, les variantes autonomes **sous-estiment
>   le coût des fortes pentes** et deviennent **trop optimistes** (surtout le 8b). Ne pas prendre
>   ces colonnes pour des temps réalistes : la référence crédible reste la baseline / « Générer ».

### Commandes utiles (`make help`)

| Commande | Rôle |
|---|---|
| `make dev` | Stack complète (Ollama + backend + front) |
| `make run` / `make front` | Backend seul / front seul |
| `make check` | lint + types + tests (comme la CI) |
| `make eval` | Évalue le LLM vs baseline sur des parcours types |
| `make migrate` | Applique les migrations Alembic (Neon) |

## Moteurs LLM

Un **adapter OpenAI-compatible unique** sert les deux providers. Les moteurs sont **fixés** par
usage (pas de bascule à faire) :

- **Production (« Générer »)** → **DeepSeek-V3** via **HF Inference** (`COMPARE_HF_MODEL`,
  `HF_TOKEN` *fine-grained* avec la permission *Inference Providers*).
- **Banc d'essai (« Comparer »)** → **llama3.1:8b** en **local Ollama** (`COMPARE_LOCAL_MODEL`) +
  DeepSeek-V3 (HF).

> Les variables `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` ne pilotent plus que l'endpoint
> historique `POST /strategy` (pipeline simple à une stratégie) et `make eval`.

## Qualité

- **~140 tests** (pytest, respx pour mocker l'HTTP), **mypy strict**, **ruff** (lint + format).
- **CI GitHub Actions** : lint + types + tests à chaque push/PR ; hooks `pre-commit` à la racine
  (`.pre-commit-config.yaml`). Le projet Python est **unique, géré à la racine** ; `backend/` et
  `front/` sont des dossiers de sources.
- **Garde-fous + fallback** : aucune réponse aberrante servie ; dégradation gracieuse si une source KO.
- **Monitoring** : métriques de production journalisées (volume, % IA vs repli baseline,
  % personnalisées par la calibration, écart à la baseline, latence) — `/stats` + page Monitoring.

## API (extrait)

`GET /health` · `POST /strategy/generate` (reco ancrée) · `POST /strategy/compare` (banc d'essai) ·
`GET /calibration` + `POST /calibration/refresh` (données COROS) · `POST /profile` · `GET /weather` ·
`GET /athlete` · `GET /history` · `GET /history/{id}` · `GET /stats` · `POST /strategy` (pipeline
simple) — endpoints protégés par token Bearer.

## Suivi de projet & livrables

- Livrables d'évaluation (conduite de projet) dans [`docs/`](docs/) : besoins (C1), audit data (C2),
  solution technique & ADR (C3).
- Board : [GitHub Projects](https://github.com/users/XavierCoulon/projects/6).
