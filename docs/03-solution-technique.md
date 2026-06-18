# 03 — Solution technique & décisions (C3)

> Livrable de la compétence **C3 — Identifier une solution technique répondant aux besoins**.
> Regroupe les décisions d'architecture sous forme d'**ADR** (Architecture Decision Records).
> Construit incrémentalement : **C-ADR1** (orchestration), C-ADR2 (client COROS), C-ADR3 (LLM/provider).

## ADR-1 — Orchestrateur déterministe vs agent LLM autonome

- **Statut** : Accepté
- **Compétence** : C3

### Contexte

Le besoin (C1) est de produire une **stratégie d'allure km par km** fiable à partir d'un GPX enrichi
(altitudes, forme COROS, météo, surface). Deux approches possibles :
1. **Agent LLM autonome** : le LLM décide lui-même quels outils/sources appeler et orchestre le pipeline.
2. **Orchestrateur déterministe** : un backend FastAPI prépare et nettoie la donnée selon un pipeline
   fixe, et le LLM ne fait **que produire le JSON de stratégie** à partir d'une donnée déjà consolidée.

### Décision

On retient l'**orchestrateur déterministe**. Le backend pilote le pipeline (parsing GPX → nettoyage
altitudes → enrichissements → baseline → génération) ; le LLM (Llama 3.1 8B) intervient **uniquement**
en fin de chaîne pour générer un **JSON de stratégie validé par Pydantic**, à partir de la seule donnée
nettoyée injectée dans le prompt.

### Conséquences

**Positives**
- **Prédictibilité & testabilité** : pipeline déterministe, chaque étape testable indépendamment.
- **Robustesse** : dégradation gracieuse maîtrisée + **fallback baseline** déterministe si le LLM échoue.
- **Coût & latence maîtrisés** : un seul appel LLM, pas de boucles d'agent.
- **Garde-fous métier** appliqués sur la sortie LLM (bornes physiologiques).

**Négatives / limites**
- Moins « flexible » qu'un agent : ajouter une source = ajouter une étape au pipeline (port/adapter).
- L'intelligence reste cadrée par l'orchestration ; le LLM ne peut pas « improviser » de stratégie de collecte.

> Cohérent avec l'architecture cible du projet (Clean Architecture, ports/adapters) et les exigences
> non-fonctionnelles de fiabilité de sortie (cf. `01-cadrage-besoins.md`, NFR).

## ADR-2 — Client COROS : httpx maison vs SDK MCP officiel

- **Statut** : Accepté (issu du spike #13)
- **Compétence** : C3

### Contexte

La forme athlète (priorité 1) provient du **serveur MCP distant COROS** (`https://mcpeu.coros.com/mcp`),
accessible via OAuth 2.1. Deux façons de s'y connecter depuis le backend :
1. **SDK MCP officiel** (`mcp` Python) — la voie standard, haut niveau.
2. **Client httpx maison** — requêtes HTTP directes (`initialize` → `tools/call`, parsing du flux SSE).

Le **spike d'authentification** a validé l'auth (GO) mais a révélé un **bug bloquant du SDK officiel**
sur COROS : le SDK `mcp` gère mal le flux **GET SSE concurrent** côté serveur COROS et bloque.

### Décision

On implémente un **client MCP httpx maison** (`coros_client.py`) qui reproduit le strict nécessaire du
protocole MCP : `initialize` → `tools/call`, header `Accept: application/json, text/event-stream`,
parsing du `text/event-stream`. Le SDK officiel est écarté pour COROS.

### Conséquences

**Positives**
- **Débloque** l'accès aux données COROS, prouvé par le spike.
- **Contrôle total** sur les requêtes/timeouts/retries, isolé dans un adapter (`AthleteProvider`).
- Surface de dépendances réduite côté COROS.

**Négatives / limites**
- **Maintenance** : à réaligner si COROS fait évoluer son protocole.
- Réimplémente une partie de ce que ferait le SDK → tests dédiés nécessaires (parsing SSE mocké).
- À surveiller : durée de vie réelle du **refresh token** (renouvellement auto).

> Détail technique conservé en mémoire projet (bug SDK `mcp` sur COROS). Le `AthleteProvider` a deux
> implémentations : réelle (via `coros_client`) + mock seedé pour tests/offline.

## ADR-3 — Choix du LLM & du provider (Llama 3.1 8B / Hugging Face)

- **Statut** : Accepté
- **Compétence** : C3

### Contexte

Le LLM intervient en fin de pipeline (cf. ADR-1) pour générer le **JSON de stratégie**. Besoin : un
modèle capable de **sortie JSON structurée** fiable, à **coût quasi nul** (projet perso/portfolio),
hébergeable simplement aux côtés du backend (HF Spaces). Options envisagées :
1. **API propriétaire** (GPT/Claude) — qualité élevée mais coût récurrent + dépendance fournisseur.
2. **Modèle local** (Ollama) — gratuit mais hardware/latence sur Space CPU.
3. **Modèle ouvert via HF Inference Providers** — Llama 3.1 8B Instruct, endpoint chat completions.

### Décision

On retient **`meta-llama/Llama-3.1-8B-Instruct`** servi via **Hugging Face Inference Providers**
(routé, ex. DeepInfra), appelé avec `huggingface_hub.InferenceClient` (endpoint **chat completions
OpenAI-compatible**, `response_format` JSON). **Ollama local** reste un fallback optionnel hors-ligne.

### Conséquences

**Positives**
- **Coût ~0 €** à notre échelle : ~0,01–0,03 c/requête, couvert par le crédit gratuit (~300–900 req/mois).
- **Sortie JSON** native (`response_format`) + validation Pydantic + retry → fiabilité de sortie.
- **Cohérence d'hébergement** : même écosystème que le Space (secret `HF_TOKEN`), pas de GPU à gérer.
- Modèle **ouvert**, reproductible, pas de verrouillage propriétaire.

**Négatives / limites**
- Qualité d'un 8B < gros modèles propriétaires → **garde-fous métier + fallback baseline** indispensables.
- **Modèle gated** : licence à accepter + token fine-grained (prérequis HF1–HF5, délai d'approbation possible).
- Dépendance à la disponibilité/tarif du provider routé (à surveiller, C5).

> Garde-fous et fallback : voir ADR-1 et `01-cadrage-besoins.md` (NFR fiabilité). Suivi coût/dispo : C5.
