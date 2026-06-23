# PaceRunner 🏃

Application web full-stack générant des **stratégies de course à pied prédictives** (allure km par km)
à partir d'un fichier **GPX**, d'un orchestrateur déterministe **FastAPI** et d'un LLM **Llama 3.1 8B**.

Projet final P15 — formation IA. Géré « comme en entreprise » et évalué sur 5 compétences de
**conduite de projet IA** (besoins métiers, audit data, solution technique, appui décision, contrôle).

## Architecture (cible)

```
GPX ─▶ FastAPI (orchestrateur déterministe)
        ├─ parsing & nettoyage altitudes (Open Topo Data)
        ├─ forme athlète (COROS via MCP)
        ├─ météo + qualité air jour J (Open-Meteo)
        ├─ surface du parcours (Overpass / OSM)
        ├─ baseline déterministe (fallback + référence)
        └─ Llama 3.1 8B (HF Inference) → stratégie JSON validée (Pydantic)
                                          └─ journalisée (Neon Postgres)
Front Streamlit ─▶ profil dénivelé, allure conseillée, tableau km/km, historique, monitoring
```

## Stack

Python · FastAPI · Pydantic · Streamlit · `huggingface_hub` (Llama 3.1 8B) · SQLModel/Neon Postgres ·
client MCP COROS maison (httpx) · `uv` · Docker · GitHub Actions · Hugging Face Spaces.

## Choisir le moteur LLM (local ou HF)

La génération passe par un **adapter OpenAI-compatible unique** ; on bascule par 3 variables
d'environnement (cf. `.env`), sans changer le code.

**Local — Ollama** (défaut, gratuit, hors-ligne) :
```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.1:8b
LLM_API_KEY=
```
Prérequis : `ollama serve` + `ollama pull llama3.1:8b` (le `make dev` lance Ollama si besoin).

**HF Inference** (le modèle est servi par Hugging Face) :
```env
LLM_BASE_URL=https://router.huggingface.co/v1
LLM_MODEL=meta-llama/Llama-3.1-8B-Instruct
LLM_API_KEY=hf_xxxxxxxxxxxxxxxxxxxxxxxx
```
Prérequis : compte HF, accès au modèle *gated* `meta-llama/Llama-3.1-8B-Instruct` accepté, et un
**token fine-grained** avec la permission *« Make calls to Inference Providers »*
(https://huggingface.co/settings/tokens). On peut cibler un fournisseur/politique via un suffixe de
modèle (ex. `meta-llama/Llama-3.1-8B-Instruct:cheapest`).

## Suivi de projet

Voir le [board GitHub Projects](https://github.com/users/XavierCoulon/projects/6) et les livrables dans [`docs/`](docs/).

## Statut

🚧 En cadrage (backlog + docs de besoins). Implémentation incrémentale ensuite, phase par phase.
