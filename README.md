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

## Suivi de projet

Voir le [board GitHub Projects](https://github.com/users/XavierCoulon/projects/6) et les livrables dans [`docs/`](docs/).

## Statut

🚧 En cadrage (backlog + docs de besoins). Implémentation incrémentale ensuite, phase par phase.
