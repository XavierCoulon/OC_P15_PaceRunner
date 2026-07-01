# Rapport de conduite de projet AI Engineering — **PaceRunner**

> Projet P15 (formation AI Engineer). Application de **stratégies de course à pied prédictives** :
> à partir d'un fichier **GPX** et d'une date de course, l'app génère une **allure conseillée
> km par km**, personnalisée selon la **forme du coureur** (montre COROS) et la **météo jour J**.
>
> Dépôt : <https://github.com/XavierCoulon/OC_P15_PaceRunner> · Board :
> <https://github.com/users/XavierCoulon/projects/6>

---

## 1. Contexte et analyse des besoins

### 1.1 Présentation (organisation / contexte)

- **Secteur & contexte** : *running / trail tech* grand public. Le projet est **personnel**
  (portfolio d'ingénieur IA) mais conduit **« comme en entreprise »** : un coureur amateur-confirmé
  veut, avant une course qu'il ne connaît pas encore, une **stratégie d'allure réaliste** tenant
  compte du dénivelé, de sa forme et de la météo — au lieu d'un simple « temps cible » moyen.
- **Taille de l'organisation** : **mono-utilisateur**. La personne concernée est à la fois
  l'utilisateur, le propriétaire des données et le responsable de traitement → **surface RGPD
  réduite** mais **données de santé** (COROS) réelles.
- **Maturité IA / MLOps** : projet **greenfield** (aucun existant). Positionnement **AI Engineer /
  mise en production** dès le départ : orchestration cadrée, **journalisation des prédictions**,
  **monitoring du modèle**, **CI/CD**, tests automatisés.
- **Contraintes** :
  - **Coût** : rester à **~0 €** (projet perso) → modèles gratuits (local Ollama / crédits HF),
    API sans clé, base *free tier*.
  - **Sécurité / réglementaire** : données de santé COROS (RGPD), secrets hors dépôt, auth API.
  - **Fiabilité** : dépendance à plusieurs **API externes** faillibles → **jamais** servir une
    allure aberrante, dégradation gracieuse si une source tombe.
  - **Infra** : pas de cloud (livrable = **portfolio + dépôt GitHub**), exécution **locale**.

### 1.2 Collecte et analyse du besoin métier

- **Parties prenantes** :
  - *Utilisateur principal* : le **coureur** (persona « Xavier », trail/route).
  - *Persona secondaire* : le **coach** (lecture d'un plan par tranche).
  - *Accompagnement* : mentors — méthode « comme en entreprise » et **angle MLOps**
    (journalisation, monitoring, CI/CD).
- **Recueil du besoin** : **personas + user stories** (épic A), **cahier des besoins** cadré en
  **QQOQCCP** (`docs/01-cadrage-besoins.md`), **backlog produit** GitHub (tickets métier +
  techniques), **ADR** pour les décisions structurantes.
- **Objectifs visés** :
  - *Métier* : un **assistant de pacing** qui produit une allure km/km **réaliste et personnalisée**,
    avec une **explication** compréhensible (plan par tranche).
  - *Technique* : orchestrateur **déterministe** + **LLM cadré** (sortie JSON validée, garde-fous,
    repli), personnalisation à partir de l'**historique COROS**, monitoring en production.
- **Contraintes réglementaires / éthiques / sécurité** : RGPD (données de santé, minimisation,
  droit à l'effacement trivial en mono-user), pas de revente/partage, **secrets** (token COROS/HF)
  hors dépôt, endpoints protégés par token Bearer.
- **Hiérarchisation (matrice impact / effort)** :

  | Besoin | Impact | Effort | Décision |
  |---|---|---|---|
  | Baseline déterministe (allure km/km réaliste) | Fort | Moyen | **MVP** (valeur immédiate + sert de référence/repli) |
  | Enrichissements (altitude, COROS, météo) | Fort | Moyen | Priorisé (précision) |
  | Couche LLM ancrée (tactique + narratif) | Moyen-Fort | Moyen | Priorisé après baseline |
  | Calibration personnalisée (historique COROS) | Fort | Fort | Itération dédiée (épic #76) |
  | Courbe de pente perso (axe D, flux détaillés) | Faible-Moyen | Fort | **Reporté** (données trail insuffisantes) |
  | Déploiement cloud / conteneurisation | Faible (portfolio) | Moyen | **Hors périmètre** |

---

## 2. Audit de la solution data (proposée — pas d'existant)

### 2.1 Solution proposée

Aucune solution existante → **architecture cible construite from scratch**. Flux de données :

```
Historique COROS ─▶ calibration (allures distance · chaleur · forme) ─▶ Neon
GPX + date ─▶ FastAPI (orchestrateur déterministe)
               ├─ parsing GPX + nettoyage altitudes (Open Topo Data)
               ├─ forme du jour (COROS via client MCP httpx maison)
               ├─ météo jour J (Open-Meteo : prévision / climatologie ERA5)
               ├─ baseline déterministe CALIBRÉE (Minetti + facteurs perso)
               └─ LLM DeepSeek-V3 ancré (tactique ±20 % + narratif)
                    └─ garde-fous + validation Pydantic → PaceStrategy → Neon
Front Streamlit ─▶ Données COROS · Génération · Historique · Monitoring
```

**Sources de données** :

| Source | Rôle | Accès |
|---|---|---|
| **GPX** (fichier coureur) | tracé + dénivelé | upload |
| **COROS** (montre) | forme du jour + **historique de courses** | **MCP** (client httpx maison, OAuth) |
| **Open Topo Data** | altitudes terrain (corrige le bruit baro GPX) | API REST (gratuite) |
| **Open-Meteo** | météo jour J + **climatologie ERA5** (calibration chaleur) | API REST (gratuite) |

**Outils / technos** : **FastAPI**, **Pydantic / SQLModel**, **Neon Postgres** + **Alembic**,
client **MCP COROS** maison (httpx), LLM **OpenAI-compatible** (Ollama local / HF Inference),
front **Streamlit** (pydeck, Altair), `uv` · ruff · mypy strict · pytest · GitHub Actions.

### 2.2 Évaluation de l'adéquation aux besoins

| Critère | Constat | Levier retenu |
|---|---|---|
| **Performance** | baseline instantanée ; LLM DeepSeek ~10 s/génération | calibration **précalculée** (0 appel COROS sur le chemin de génération) |
| **Robustesse** | API externes faillibles (COROS *flaky*, Open Topo Data parfois KO) | **dégradation gracieuse** partout + **retry/timeout** COROS + **repli baseline** |
| **Sécurité / RGPD** | données de santé (FC, forme, localisation) | mono-user, secrets hors dépôt, **minimisation** (résumés + agrégats, **jamais** de flux haute résolution) |
| **Coût** | quasi nul | Ollama local (gratuit), DeepSeek via **crédits HF gratuits**, API sans clé, **Neon free tier** |
| **Maintenance** | Clean Architecture (ports/adapters) | remplacement d'un adapter sans toucher au métier |
| **Monitoring** | besoin MLOps (C5) | journal `prediction_runs` + page **Monitoring** (`GET /stats`) |

**Écarts / limites identifiés** :
- **COROS** intermittent (sessions MCP en rafale) → *retry + timeout élargi* + **filet** : si l'allure
  seuil du jour manque, la baseline reprend l'**ancre stockée dans la calibration**.
- **LLM 8B** décroche sur terrain raide (sous-estime le coût des pentes) → passage à **DeepSeek-V3**
  en production, le 8B reste comme **bras de comparaison**.
- **Axe D** (courbe allure-pente perso) **non faisable** : seulement 9 courses trail en base.
- **FC moyenne** collectée mais **non encore exploitée**.

---

## 3. Identification d'une solution technique cible

### 3.1 Comparatif d'approches (avantages / inconvénients)

**a) Orchestration : déterministe vs agent LLM autonome** (ADR-1)

| Approche | + | − | Décision |
|---|---|---|---|
| **Agent LLM autonome** (décide des outils, calcule tout) | flexible | non reproductible, hallucinations, coûteux à valider | ❌ |
| **Orchestrateur déterministe + LLM cadré** | reproductible, testable, robuste | moins « magique » | ✅ **retenu** |

→ La **physique au km est 100 % déterministe** (baseline calibrée, modèle de **Minetti** pour la
pente) ; le **LLM n'ajoute que la tactique bornée (±20 %) + le narratif**, avec **garde-fous + repli**.

**b) Choix du LLM & du provider** (ADR-3/4/5)

| Option | + | − | Décision |
|---|---|---|---|
| API propriétaire (GPT/Claude) | qualité | coût récurrent, dépendance | ❌ |
| Modèle local (Ollama) | gratuit, hors-ligne | latence CPU | ✅ dev/CI + banc d'essai |
| Modèle ouvert via **HF Inference** | coût ~0, JSON fiable | dépendance provider | ✅ **prod (DeepSeek-V3)** |

→ **Production = `deepseek-ai/DeepSeek-V3-0324` (HF Inference)** ; **banc d'essai = llama3.1:8b
(Ollama) + DeepSeek CoT**.

### 3.2 Schéma d'architecture cible

```
                    ┌──────────────── Front Streamlit (Bearer) ────────────────┐
                    │  Données COROS · Génération · Historique · Monitoring     │
                    └───────────────┬───────────────────────────┬──────────────┘
                                    │ HTTPS + token             │
                    ┌───────────────▼───────────────────────────▼──────────────┐
                    │                    FastAPI (Clean Arch)                    │
   adapters ◀──────▶│  domain (modèles + ports)  ·  services (orchestrateur,     │
   GPX/OTD/COROS/   │  baseline calibrée, calibration, garde-fous, qualité)      │
   Open-Meteo/LLM   └───────────────┬───────────────────────────┬──────────────┘
                                    │                           │
                         Neon Postgres (SQLModel/Alembic)   LLM OpenAI-compatible
                  coros_activities · calibration_snapshots   DeepSeek-V3 (HF) /
                  · prediction_runs                          llama3.1:8b (Ollama)
```

### 3.3 Justification des choix technologiques

- **FastAPI** : API async typée, injection de dépendances (facilite le test et le remplacement
  d'adapters), sécurité Bearer.
- **Pydantic / SQLModel** : contrats stricts (sortie LLM **validée**), mapping DB unifié.
- **Neon Postgres + Alembic** : Postgres *serverless free tier*, migrations versionnées.
- **Client MCP COROS maison (httpx)** : le SDK officiel bloque sur COROS → transport Streamable
  HTTP réécrit (auth OAuth + refresh token roté).
- **LLM OpenAI-compatible** : un **seul adapter**, bascule Ollama ↔ HF par configuration.
- **Streamlit** (pydeck/Altair) : front data rapide (carte, courbes, tableaux).
- **`uv` · ruff · mypy strict · pytest · GitHub Actions** : qualité « comme en entreprise ».

### 3.4 Méthodologie d'identification / priorisation des cas d'usage

Backlog produit **découpé en épics** (work-breakdown A→N), chaque ticket porté par une **user story**
(valeur métier) ou une **tâche** (moyen technique), priorisé par **matrice valeur/effort** (cf. §1.2)
et ordonné par **jalons**. Décisions structurantes tracées en **ADR**.

---

## 4. Stratégie de mise en œuvre et d'industrialisation

### 4.1 Démarche projet

**Roadmap par phases** (méthode : *cadrage avant code* — tout le backlog + docs de besoins avant
d'implémenter, puis **itérations validées** phase par phase) :

| Phase | Contenu | Outils |
|---|---|---|
| **Cadrage** | board + labels + jalons + **backlog complet** ; docs besoins (C1/C2) | GitHub Projects, Markdown |
| **Spike COROS** | valider l'accès data (go/no-go) | client MCP httpx |
| **Socle** | archi, config, CI, auth | FastAPI, uv, ruff, mypy, GitHub Actions |
| **Pipeline** | GPX → altitudes → COROS → météo → baseline | Open Topo Data, Open-Meteo |
| **IA** | LLM ancré, garde-fous, repli, éval | Ollama/HF, respx |
| **Persistance** | journalisation + KPIs | Neon, Alembic |
| **Front** | génération, historique, monitoring | Streamlit |
| **Itérations** | calibration COROS, robustesse, UX | — |
| **Clôture** | durcissement, livrables, soutenance | — |

**Découpage dev → industrialisation** : développement (TDD léger, LLM stubé) → **tests**
(unitaires + intégration + E2E via respx) → **CI bloquante** (ruff + mypy strict + pytest à chaque
push/PR) → **migrations** (Alembic) → **monitoring** (journalisation + `/stats`). *Conteneurisation
Docker et déploiement cloud volontairement hors périmètre* (livrable portfolio, exécution locale
`make dev` ; HF Spaces envisageable).

### 4.2 Aide à la prise de décision

**Risques / opportunités & atténuations** :

| Risque / impact | Type | Atténuation |
|---|---|---|
| Données de santé COROS | **RGPD / éthique** | mono-user, minimisation, jamais de flux haute résolution, secrets hors dépôt |
| LLM optimiste sur pentes raides (biais) | **Qualité / biais** | ancrage baseline + garde-fou ±20 % + repli déterministe |
| Latence LLM (~10 s) | **Perf / UX** | calibration précalculée, forme+météo affichées **avant** l'attente |
| Dépendance provider HF / COROS | **Fournisseur** | adapter unique bascule Ollama, retry/timeout, dégradation gracieuse |
| Hallucination du narratif | **Fiabilité** | découpage **déterministe** côté serveur (bornes figées) + repli |

**Scénarios budgétaires** :

| Poste | Choix | Coût |
|---|---|---|
| Calcul LLM (prod) | DeepSeek-V3 via HF Inference | **crédits mensuels gratuits** (≈ 1 appel ~10 s/génération) |
| Calcul LLM (banc d'essai) | llama3.1:8b **local** (Ollama) | 0 € |
| API données | Open Topo Data, Open-Meteo, COROS (compte perso) | 0 € |
| Base de données | Neon Postgres **free tier** | 0 € |
| Hébergement | local (`make dev`) | 0 € |

→ **Coût d'infrastructure ≈ 0 €** à l'échelle démo (marge négligeable au-delà des crédits HF ;
bascule possible sur un modèle **local** pour un 0 € garanti).

**Indicateurs de succès (KPI)** :
- *Métier* : allure km/km **réaliste** (crédible vs temps de référence), plan par tranche lisible.
- *Technique* : **% IA acceptée vs repli baseline**, **écart moyen à la baseline**, **% générations
  personnalisées** (calibration), **latence**, CI verte, couverture de tests.

---

## 5. Contrôle et suivi du projet

### 5.1 Tableau de bord de pilotage

**Méthodologie de gestion** : **Kanban** (GitHub Projects) + **DevOps** (une branche + une PR par
ticket, revue, CI bloquante, merge après validation). **Traçabilité** : besoin → ticket → branche →
PR → CI → merge. Décisions → **ADR**.

**Volumétrie à date** :

| Indicateur | Valeur |
|---|---|
| Issues | **71** (62 fermées / 9 ouvertes) |
| Pull Requests | **11** (4 mergées, 1 fermée, 6 ouvertes — pile calibration) |
| Tests automatisés | **~141** (CI verte) |
| Épics (work-breakdown) | A→N + HF + incréments thématiques |

**Répartition** : *par type* — 32 tâches, 25 US, 5 docs, 3 ADR, 1 spike ; *par domaine* —
57 technique / 9 métier ; *par compétence* — C1 = 3, C2 = 6, C3 = 15, C5 = 11.

**KPIs de suivi** : *délais* (jalons/phases, avancement des épics) · *coûts* (≈ 0 €, cf. §4.2) ·
*livrables* (docs C1–C5, code, tests) · *performance* (latence, % IA vs repli, écart baseline —
page Monitoring).

### 5.2 Outils et process de suivi

- **Monitoring en production** : journal **`prediction_runs`** (Neon) + endpoint **`GET /stats`** +
  page **Monitoring** Streamlit (volume, **% IA vs repli**, **% personnalisées**, écart baseline,
  **latence**). *(Logs structurés custom ; Prometheus/Grafana hors périmètre à cette échelle.)*
- **Méthodologie de test & évaluation** :
  - **Tests unitaires** (services purs : baseline, calibration, parsing, métriques).
  - **Tests d'intégration / E2E** (`respx` mocke les API externes ; pipeline complet avec vrais
    adapters).
  - **Tests d'endpoints** (FastAPI TestClient, auth, cas d'erreur).
  - **Jeu d'évaluation** `make eval` (parcours types : plat / vallonné / long) comparant **LLM vs
    baseline**.
  - *Tests de charge : hors périmètre (mono-utilisateur, pas de SLA production).*
- **CI/CD** : **GitHub Actions** (ruff + mypy strict + pytest) à chaque push/PR ; hooks `pre-commit`.

---

## 6. Conclusion & recommandations

**Choix clés** :
- **Orchestrateur déterministe + LLM cadré** : la physique (Minetti + calibration) est déterministe,
  reproductible, testable ; le LLM n'ajoute que **tactique bornée + narratif**, avec **garde-fous +
  repli**.
- **Personnalisation par l'historique COROS** (calibration précalculée : allures par distance,
  sensibilité chaleur, forme) → allures **réalistes et personnelles**, sans coût sur le chemin de
  génération.
- **DeepSeek-V3 en production** (après constat que le 8B décroche), 8B conservé en **banc d'essai**.
- **Robustesse par dégradation gracieuse** de bout en bout.

**Perspectives d'évolution** :
- **Axe D** (courbe allure-pente personnelle) quand le volume de trails augmentera.
- **Exploiter la FC** (déjà collectée) : dérive cardiaque, effort soutenable.
- **Déploiement** HF Spaces + éventuelle **conteneurisation** si passage multi-utilisateur.
