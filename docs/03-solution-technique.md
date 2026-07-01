# 03 — Solution technique & décisions (C3)

> Livrable de la compétence **C3 — Identifier une solution technique répondant aux besoins**.
> Regroupe les décisions d'architecture sous forme d'**ADR** (Architecture Decision Records).
> ADR-1 (orchestration) · ADR-2 (client COROS) · ADR-3 & ADR-4 (LLM/provider) · **ADR-5** (évolution :
> calibration personnalisée, DeepSeek-V3 en production, deux flux Générer/Comparer).

> **⚠️ État courant** : le **modèle de production est DeepSeek-V3** (le 8B n'est plus que le bras de
> comparaison), et une **couche de calibration** personnalise la baseline. Les ADR-3/ADR-4 ci-dessous
> décrivent le choix **initial** (Llama 3.1 8B / HF vs local) et sont **partiellement supersédés par
> l'ADR-5** (en fin de document). Le projet **n'est pas déployé** (exécution locale, livrable portfolio).

## ADR-1 — Orchestrateur déterministe vs agent LLM autonome

- **Statut** : Accepté
- **Compétence** : C3

### Contexte

Le besoin (C1) est de produire une **stratégie d'allure km par km** fiable à partir d'un GPX enrichi
(altitudes, forme COROS, météo). Deux approches possibles :
1. **Agent LLM autonome** : le LLM décide lui-même quels outils/sources appeler et orchestre le pipeline.
2. **Orchestrateur déterministe** : un backend FastAPI prépare et nettoie la donnée selon un pipeline
   fixe, et le LLM ne fait **que produire le JSON de stratégie** à partir d'une donnée déjà consolidée.

### Décision

On retient l'**orchestrateur déterministe**. Le backend pilote le pipeline (parsing GPX → nettoyage
altitudes → enrichissements → baseline → génération) ; le **LLM** (initialement Llama 3.1 8B, désormais
**DeepSeek-V3** en production — cf. ADR-5) intervient **uniquement** en fin de chaîne pour générer un
**JSON de stratégie validé par Pydantic**, à partir de la seule donnée nettoyée injectée dans le prompt.

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

- **Statut** : Accepté — **partiellement supersédé par [ADR-5](#adr-5--calibration-personnalisée--deepseek-v3-en-production-évolution)** (modèle de prod = DeepSeek-V3)
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

## ADR-4 — LLM local (Ollama) d'abord, Hugging Face ensuite

- **Statut** : Accepté — **partiellement supersédé par [ADR-5](#adr-5--calibration-personnalisée--deepseek-v3-en-production-évolution)** (prod = DeepSeek-V3 ; le local reste le banc d'essai)
- **Compétence** : C3

### Contexte

Développer et tester tout le pipeline contre HF Inference suppose les prérequis HF1–HF5 (compte,
modèle gated, token, provider) — délai d'approbation possible et dépendance réseau pour chaque test.
Or **Ollama** et **HF Inference** exposent tous deux une API **OpenAI-compatible** (`/v1/chat/completions`).

### Décision

On développe et teste d'abord la génération avec un **modèle local via Ollama** (`llama3.1:8b`, soit
**le même modèle** que la cible prod `meta-llama/Llama-3.1-8B-Instruct`). On écrit **un seul adapter LLM
OpenAI-compatible** (`StrategyGenerator`) dont on bascule la cible **par configuration**
(`base_url` + `model` + clé) : local en dev/CI offline, **HF en prod**. Les prérequis HF (HF1–HF5)
passent **après** la validation locale.

### Conséquences

**Positives**
- **Itération rapide et hors-ligne** : pas de réseau, pas de quota, coût nul en dev/tests.
- **Même modèle local et prod** → prompt et comportement JSON validés en local transposables tels quels.
- **Bascule local↔HF par simple config**, sans re-travail du code.
- Tests déterministes (LLM stubé) inchangés ; un test d'intégration local optionnel possible.

**Négatives / limites**
- Ollama à installer/lancer en local (déjà fait : M3 Pro 18 Go, `llama3.1:8b` ≈ 4,9 Go).
- Légères différences possibles de tokenizer/quantification local vs provider HF → revalider en prod.

> Reste cohérent avec ADR-3 (même modèle 8B, garde-fous + fallback baseline). HF devient une **cible de
> déploiement** plutôt qu'une dépendance de développement.

---

## ADR-5 — Calibration personnalisée + DeepSeek-V3 en production (évolution)

- **Statut** : Accepté (supersede partiellement ADR-3/ADR-4 sur le modèle de prod)
- **Compétence** : C3

### Contexte

Deux constats après les premières versions : (1) la baseline ancrée sur la seule allure seuil COROS
restait générique (facteurs de distance/pente/chaleur issus de la littérature) ; (2) le 8B en mode
autonome décrochait sur terrain raide. On dispose par ailleurs d'un **historique COROS riche**
(≈ 1300 courses).

### Décision

1. **Calibration personnalisée (#76)** : on ingère l'historique COROS (`querySportRecords`, batch +
   incrémental) + la météo historique ERA5, et on en dérive un **profil de calibration** persisté
   (`coros_activities`, `calibration_snapshots`) : allures de référence par distance (meilleurs
   efforts réels), **sensibilité chaleur** (résidu d'allure vs température), tendance de forme (ACWR).
   La baseline reste ancrée sur le **seuil COROS** mais ses multiplicateurs deviennent **perso**.
2. **Rôles LLM** : en production, le LLM est **ancré** sur la baseline calibrée → tactique bornée
   (±20 %, negative split) + **narratif par tranche** (découpage déterministe côté serveur,
   anti-hallucination). La physique au km reste déterministe.
3. **Modèle de production = `deepseek-ai/DeepSeek-V3-0324`** (HF Inference) : nettement plus fiable
   que le 8B sur la sortie JSON et le raisonnement tactique. Le **8B local (Ollama)** reste, mais
   comme **bras de comparaison autonome** dans le banc d'essai (#74), aux côtés de DeepSeek CoT.
4. **Deux flux front** : « **Générer** » (production, reco ancrée DeepSeek, journalisée) et
   « **Comparer** » (banc d'essai brut, non journalisé).

### Conséquences

**Positives**
- Allures **réalistes et personnelles** (ex. facteurs distance ×1.17–1.44 mesurés vs génériques) ;
  robustesse accrue (filet : si l'allure seuil du jour manque, on reprend l'ancre de la calibration).
- Séparation nette **physique (déterministe) / tactique + narratif (LLM)** → plus testable.
- La calibration est **précalculée** : zéro appel COROS sur le chemin `/strategy/generate`.

**Négatives / limites**
- Dépendance à HF Inference pour la prod (crédits gratuits suffisants à l'échelle démo).
- Axe D (courbe de pente perso via flux détaillés) **reporté** : trop peu de trails en base.
- FC moyenne et `resting_hr` collectés mais **non encore exploités**.
