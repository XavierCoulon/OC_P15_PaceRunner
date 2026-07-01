# 02 — Audit data & sources (C2)

> Livrable de la compétence **C2 — Auditer la solution data afin d'en déterminer l'adéquation
> avec les besoins**. Construit incrémentalement : **B1** (inventaire), B2 (qualité/limites), B3 (RGPD).

## B1 — Inventaire des sources de données

### Vue d'ensemble

| Source | Données fournies | Accès / protocole | Auth | Rôle dans le pipeline | Priorité |
|---|---|---|---|---|---|
| **GPX** (fichier coureur) | Tracé (lat/lon), altitude barométrique, distance | Upload fichier (multipart) | — | **Entrée principale** : profil de parcours, point de départ pour la géolocalisation des autres sources | 1 (indispensable) |
| **COROS** | Forme athlète : VO2max & **allure seuil** (fitness overview), **récupération** (recovery status), **poids** (user info) | Serveur **MCP distant** via **client httpx maison** | OAuth 2.1 (mono-utilisateur, refresh token en secret) | Personnalisation de la stratégie selon la forme du propriétaire | 1 |
| **Open Topo Data** | **Altitudes corrigées** par coordonnées | API HTTP publique (REST) | — (gratuit) | Nettoyage du bruit barométrique du GPX → dénivelé fiable | 1 (nettoyage) |
| **Open-Meteo** | **Météo selon l'horizon** : prévision (≤16 j) + qualité air (≤~5 j) ; **climatologie ERA5** (>16 j, 1940→) avec repère « même date l'an dernier » | 2 API REST (forecast / archive) — seasonal SEAS5 différé | — (gratuit, sans clé) | Conditions au point de départ pour la date/heure de course | 2 |
| **Overpass / OSM** | **Type de surface** du parcours (route, sentier, piste…) | API HTTP publique (Overpass QL) | — (gratuit) | Affiner l'effort selon le revêtement | 3 |

### Notes

- **Géolocalisation** : les coordonnées du **GPX** (notamment le point de départ) alimentent Open Topo
  Data, Open-Meteo et Overpass — le GPX est donc la source pivot.
- **COROS** : seule source nécessitant une authentification ; app **mono-utilisateur** (un seul compte,
  OAuth réalisé une fois — cf. spike #13 et ADR C-ADR2). Accès via **client MCP httpx maison** (le SDK
  officiel bloque sur COROS). Le serveur **fait tourner le refresh token à chaque refresh** → stockage
  durable du token (l'access_token dure ~30 j).
- **Outils COROS retenus** (sondés en live parmi 15 disponibles) :
  - *Forme du jour* — `queryFitnessAssessmentOverview` (allure seuil, VO2max), `queryRecoveryStatus`
    (fraîcheur jour J), `queryUserInfo` (poids).
  - *Historique* — **`querySportRecords` est devenu central** (#76) : ingéré (≈ 1300 courses, batch
    puis incrémental) pour **calibrer** la baseline (allures de référence par distance, sensibilité
    chaleur, tendance de forme). On récupère par course : date, distance, durée, **allure et FC
    moyennes**, coordonnées. *(La FC est collectée mais non encore exploitée dans un calcul.)*
  - Écartés : signaux redondants de fraîcheur (HRV, sommeil, stress), `queryTrainingLoadAssessment`
    (indisponible/`isError`), `getActivityDetail`/flux détaillés (axe D « courbe de pente perso »
    **reporté**, trop peu de trails), `queryDevices`/`queryTrainingSchedule` (hors besoin).
- **Météo Open-Meteo — routage par horizon** (la course peut être dans plusieurs mois) : ≤ 16 j →
  **prévision** réelle ; au-delà → **climatologie ERA5** (moyenne de la même date calendaire sur N
  années + min/max), avec comparatif **« même date l'an dernier »** en repère. Le besoin n'est donc pas
  une « prévision » exacte lointaine mais une **attente typique + incertitude**. La tendance saisonnière
  SEAS5 (16 j–7 mois) est **différée** : la climatologie la couvre déjà sans injecter de donnée bruitée.
- **Sources publiques gratuites** (Open Topo Data, Open-Meteo, Overpass) : pas de clé requise, sous
  réserve des limites d'usage (détaillées en **B2**).
- **Priorités** : 1 = indispensable, 2/3 = enrichissement avec **dégradation gracieuse** (le pipeline
  produit une stratégie même si une source 2/3 est indisponible).

## B2 — Qualité, adéquation aux besoins & limites

### Évaluation par source

| Source | Qualité / fiabilité | Adéquation au besoin | Limites & risques |
|---|---|---|---|
| **GPX** | Tracé fiable (GPS), mais **altitude barométrique bruitée** ; fichiers hétérogènes selon la montre/app. | Couvre BF1/BF2 (parcours, profil). | Fichier corrompu/incomplet → parsing à sécuriser (erreur 422) ; altitude à corriger via Open Topo Data. |
| **COROS** | Données issues d'un appareil de mesure réel (VO2max, allure seuil) ; mises à jour régulières. | Cœur de la personnalisation (BF3). | **Source unique d'auth** ; dépend du serveur MCP COROS (dispo, expiration du refresh token) ; mono-utilisateur. |
| **Open Topo Data** | Altitudes issues de modèles MNT (ex. SRTM) — bonne précision relative pour le dénivelé. | Corrige le défaut clé du GPX (D+ fiable). | **Limite de débit** (API publique gratuite) ; résolution finie du MNT ; service tiers → dégradation possible. |
| **Open-Meteo** | Prévision fiable ≤16 j ; au-delà, climatologie représentative. | Conditions jour J (BF4), quel que soit l'horizon. | Routage : ≤16 j **prévision** · au-delà **climatologie ERA5** (moyenne N années + min/max, + même date l'an dernier). Qualité air ≤~5 j. Seasonal SEAS5 **différé** (bruité/non bias-corrigé). |
| **Overpass / OSM** | Données contributives : couverture/qualité **variables** selon la zone. | Affine l'effort (revêtement) — apport secondaire. | Tags surface parfois absents/incohérents ; **quotas** Overpass ; service tiers. |

### Synthèse d'adéquation

- **Suffisant pour le besoin** : GPX + COROS + Open Topo Data couvrent les besoins critiques (BF1–BF3).
  Open-Meteo et Overpass apportent un **enrichissement** (BF4) non bloquant.
- **Stratégie de robustesse** : sources de priorité 2/3 traitées en **dégradation gracieuse** ; correction
  systématique de l'altitude GPX ; garde-fous métier + **fallback baseline** si l'enrichissement manque.
- **Risques principaux** : dépendance à des **services tiers** (dispo, quotas) et à l'**auth COROS**
  (expiration refresh token) → à surveiller (KPIs C5) et à documenter dans les ADR (C3).

## B3 — RGPD, rétention & gestion des secrets

### Données personnelles concernées

| Donnée | Origine | Caractère personnel | Où elle vit |
|---|---|---|---|
| Forme athlète (VO2max, allure seuil, récup.) | COROS | **Donnée de santé / sportive** (sensible) | Récupérée à la volée + **snapshot** journalisé (Neon) |
| Historique de courses (date, distance, allure, **FC moy**, coords) | COROS | **Donnée de santé + localisation** (sensible) | Persisté en base — table `coros_activities` (#76), pour la calibration |
| Profil de calibration (facteurs agrégés) | Dérivé | Agrégé (peu identifiant) | Persisté — table `calibration_snapshots` |
| Tracé GPX (lat/lon) | Fichier coureur | **Localisation** (potentiellement domicile) | Traité en mémoire ; hash + métriques journalisés |
| Date/heure & lieu de course | Saisie / GPX | Localisation + habitude | Journalisé (Neon) |

### Contexte RGPD (simplifié par le mono-utilisateur)

- App **mono-utilisateur** : l'**unique personne concernée est le propriétaire**, qui est aussi le
  responsable de traitement. Pas de tiers, pas de collecte de données d'autrui → **surface RGPD réduite**.
- **Base légale** : intérêt/usage personnel du propriétaire sur ses propres données.
- **Minimisation** : on ne journalise que le **strict nécessaire** (métriques, snapshot de forme,
  contextes) ; pas de stockage du fichier GPX brut (seulement un **hash** + le profil dérivé).
  L'historique COROS (#76) élargit la surface (FC, lieux), donc on **borne** : résumés de course +
  bins agrégés + snapshot — **jamais** les flux haute résolution (FC/allure seconde-par-seconde).

### Rétention & anonymisation du journal (Neon)

- **Finalité** du journal `prediction_runs` : historique + monitoring du modèle (C5), pas de revente/partage.
- **Rétention** : durée limitée et documentée (ex. purge des runs > N mois) ; possibilité de **suppression
  totale** à la demande du propriétaire (droit à l'effacement, trivial ici car mono-user).
- **Anonymisation/pseudonymisation** : pas d'identifiant nominatif stocké ; coordonnées réduites au
  **point de départ** nécessaire (pas le tracé complet en clair) ; GPX référencé par **hash**.

### Gestion des secrets

- Secrets : `COROS_REFRESH_TOKEN`, `HF_TOKEN`, `DATABASE_URL` (Neon), `API_TOKEN`.
- **Jamais commités** : `.env` local + **`.gitignore`** (tokens du spike déjà exclus) ; en production,
  **Secrets du Space Hugging Face**.
- Accès backend protégé par **token API (Bearer)** ; `/health` public.
- **Transport chiffré** (HTTPS) vers toutes les sources et la base Neon ; refresh token COROS
  auto-renouvelé, jamais exposé au front.

### Risques résiduels & mesures

| Risque | Mesure |
|---|---|
| Fuite d'un secret | Hors dépôt + secrets gérés (Space HF) ; rotation possible des tokens. |
| Données de santé/localisation dans le journal | Minimisation, hash GPX, rétention limitée, effacement à la demande. |
| Dépendance auth COROS | Refresh token en secret, renouvellement auto, surveillance (C5). |
