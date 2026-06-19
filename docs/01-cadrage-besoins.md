# 01 — Cadrage & besoins (C1)

> Livrable de la compétence **C1 — Collecter les besoins métiers et analyser le contexte**.
> Ce document est construit incrémentalement : **A1** (ce ticket), puis A2 (périmètre) et A3 (KPIs).

## A1 — Personas & user stories

### Contexte d'usage

PaceRunner est une application **mono-utilisateur**. Le seul utilisateur est **le coureur propriétaire
de l'application**, qui dispose d'un **compte COROS**. L'authentification COROS (OAuth) est réalisée
**une seule fois** par ce propriétaire ; aucune inscription ni gestion de comptes tiers n'est prévue.

> Il n'y a donc **qu'un seul persona** : le coureur. Le rôle « coach » envisagé initialement est
> écarté du périmètre.

### Persona — « Le coureur autonome »

| Attribut | Description |
|---|---|
| **Profil** | Coureur amateur à confirmé, équipé d'une **montre COROS**, prépare une course sur un parcours **connu à l'avance** (fichier GPX). |
| **Données disponibles** | GPX du parcours · date/heure de la course · forme COROS (VO2max, **allure seuil**, récupération/fatigue). |
| **Objectif principal** | Obtenir une **stratégie d'allure km par km** réaliste et personnalisée pour le jour J. |
| **Frustrations** | Plans génériques qui ignorent le **dénivelé réel** du parcours, sa **forme du moment** et la **météo** prévue. |
| **Compétences** | À l'aise avec sa montre et l'export GPX ; cherche un outil simple, sans configuration. |

### User stories

| # | User story | Critères d'acceptation |
|---|---|---|
| US1 | En tant que coureur, je veux **uploader un GPX et saisir la date/heure** de ma course, afin d'obtenir une **stratégie d'allure km par km**. | GPX accepté ; un GPX invalide renvoie une erreur claire ; la stratégie liste une allure par kilomètre. |
| US2 | En tant que coureur, je veux **visualiser le profil de dénivelé** du parcours, afin de comprendre la difficulté à venir. | Profil altitude/distance affiché à partir du GPX nettoyé. |
| US3 | En tant que coureur, je veux que la stratégie **tienne compte de ma forme COROS** (allure seuil, fatigue/récup), afin qu'elle soit adaptée à mon niveau actuel. | Les données COROS du propriétaire sont intégrées au calcul ; si COROS est indisponible, l'app le signale et continue. |
| US4 | En tant que coureur, je veux que la stratégie **tienne compte des conditions prévues le jour J** (météo, vent, qualité de l'air), afin d'ajuster mon allure aux conditions réelles. | Conditions prévues récupérées pour la date/heure et le lieu de départ ; dégradation gracieuse si la source est indisponible. |
| US5 | En tant que coureur, je veux **consulter l'historique** de mes stratégies générées, afin de comparer mes courses dans le temps. | Les stratégies passées sont listées et consultables (cf. tickets N4 / K6). |
| US6 | En tant que coureur, je veux **savoir si la stratégie vient du modèle IA ou du repli déterministe** (baseline), afin d'avoir confiance dans la recommandation et d'en juger la fiabilité. | L'origine (`generated_by` : `llm` / `baseline`) est exposée par l'API et **affichée clairement dans le front** (ex. badge « IA » vs « repli ») ; en cas de fallback, l'utilisateur est informé que le modèle n'a pas pu produire de stratégie valide. |

### Note de périmètre

- Application **mono-utilisateur** : un seul compte COROS, pas de multi-comptes.
- **Pas de rôle coach**, pas de partage entre utilisateurs.
- Le périmètre fonctionnel détaillé (inclus / hors périmètre) est traité en **A2**.

## A2 — Cahier des besoins & périmètre

### Périmètre fonctionnel

| Dans le périmètre | Hors périmètre |
|---|---|
| Génération d'une **stratégie d'allure km par km** à partir d'un GPX + date/heure. | Multi-utilisateurs / inscription / gestion de comptes. |
| Nettoyage du dénivelé + profil du parcours. | Rôle **coach**, partage ou social. |
| Enrichissement **forme COROS** (propriétaire), **météo/qualité air** jour J. | Suivi en temps réel pendant la course / app mobile. |
| **Historique** des stratégies + **monitoring** du modèle. | Entraînement sur-mesure / planification de saison. |
| Front web (Streamlit) consommant le backend. | Autres sources de parcours que le **GPX** (Strava, saisie manuelle…). |

### Besoins fonctionnels (synthèse des US)

- BF1 — Importer un GPX + date/heure, produire une stratégie km/km (US1).
- BF2 — Afficher le profil de dénivelé (US2).
- BF3 — Intégrer la forme COROS du propriétaire (US3).
- BF4 — Intégrer les conditions prévues jour J (US4).
- BF5 — Historiser et consulter les stratégies passées (US5).

### Exigences non-fonctionnelles

| Type | Exigence |
|---|---|
| **Robustesse** | Dégradation gracieuse : si une source secondaire (météo, surface) est indisponible, le pipeline continue sans planter. |
| **Performance** | Réponse du pipeline acceptable pour un usage interactif (objectif chiffré défini en A3). |
| **Sécurité** | Accès au backend protégé par **token API (Bearer)** ; `/health` public. Secrets (COROS, HF, DB) hors dépôt. |
| **RGPD** | Les données COROS sont des **données personnelles** ; journalisation maîtrisée (rétention/anonymisation) — détaillé en **B3**. |
| **Fiabilité de sortie** | Stratégie LLM **validée par schéma (Pydantic)** + garde-fous métier, sinon **fallback baseline** déterministe. |

### Contraintes & dépendances

- **Mono-utilisateur** : un seul compte COROS, OAuth réalisé une fois (refresh token en secret).
- Sources externes : **COROS**, **Open-Meteo**, **Open Topo Data**, **Overpass/OSM** (qualité/limites en **B2**).
- Hébergement **Hugging Face Spaces** ; inférence via **HF Inference Providers** (Llama 3.1 8B).

## A3 — Critères de succès & KPIs métier

### Critères de succès

- **C-1** — Pour chaque course préparée, une **stratégie km/km exploitable** est générée de bout en bout sur des GPX réels.
- **C-2** — La stratégie est **réaliste** : allures dans les bornes physiologiques et cohérentes avec l'allure seuil COROS.
- **C-3** — L'app reste **utilisable en mode dégradé** : si une source secondaire (météo, surface) est indisponible, une stratégie est tout de même produite.

### KPIs métier

| KPI | Définition | Cible indicative |
|---|---|---|
| **Précision de prédiction** | Écart entre temps total prédit et temps réel le jour J. | < 5 % |
| **Pertinence allure** | % de stratégies respectant les garde-fous physiologiques. | ≥ 95 % |
| **Couverture data** | % de courses où forme COROS **et** météo jour J ont bien été intégrées. | ≥ 90 % |
| **Délai d'obtention** | Temps perçu pour obtenir une stratégie après upload du GPX. | < 30 s |
| **Utilité** (qualitatif) | La stratégie a-t-elle été suivie / jugée utile le jour J. | Retour positif |

> Cibles **indicatives**, affinées au fil des courses (projet personnel, validation empirique).
>
> Les KPIs **techniques / performance** (latence pipeline, % de JSON valides, coût d'inférence) sont
> traités dans `05-suivi-projet.md` (compétence C5) pour éviter le doublon.
