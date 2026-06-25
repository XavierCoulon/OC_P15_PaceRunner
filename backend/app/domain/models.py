"""Modèles de domaine (contrats Pydantic).

Ce sont les objets de valeur échangés dans le pipeline d'orchestration : profil de
parcours issu du GPX, contexte de course, enrichissements (athlète, météo, surface)
et stratégie d'allure produite. Tous immuables (`frozen=True`).

Conventions :
- allures exprimées en **secondes par kilomètre** (`*_sec_per_km`) — numérique, facile à calculer ;
- durées en **secondes** ; distances en **kilomètres** ; dénivelés en **mètres** ; pentes en **%**.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WeatherSource = Literal["forecast", "last_year"]

# Mode de génération LLM : ancré sur la baseline (prod), autonome (sans baseline), ou
# autonome avec raisonnement explicite imposé (chain-of-thought).
GenerationMode = Literal["anchored", "autonomous", "cot"]


class _Frozen(BaseModel):
    """Base immuable commune aux modèles de domaine."""

    model_config = ConfigDict(frozen=True)


class TrackPoint(_Frozen):
    """Point de tracé géolocalisé (source des enrichissements altitude/météo/surface)."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    elevation_m: float


class ElevationSegment(_Frozen):
    """Tronçon d'un kilomètre du parcours."""

    km_index: int = Field(ge=1, description="Numéro du kilomètre (1-based).")
    distance_km: float = Field(gt=0, description="Longueur du tronçon (≈ 1 km).")
    elevation_gain_m: float = Field(ge=0)
    elevation_loss_m: float = Field(ge=0)
    gradient_pct: float = Field(description="Pente moyenne du tronçon, en %.")


ElevationSource = Literal["gpx", "open_topo_data"]


class CourseProfile(_Frozen):
    """Profil de parcours dérivé du fichier GPX (après nettoyage des altitudes)."""

    distance_km: float = Field(gt=0)
    elevation_gain_m: float = Field(ge=0, description="Dénivelé positif total retenu (D+).")
    elevation_loss_m: float = Field(ge=0, description="Dénivelé négatif total retenu (D-).")
    elevation_source: ElevationSource = Field(
        default="gpx",
        description="Origine des altitudes retenues : terrain (open_topo_data) ou GPX brut.",
    )
    raw_elevation_gain_m: float = Field(
        default=0.0, ge=0, description="D+ brut (somme naïve des altitudes GPX, avant correction)."
    )
    raw_elevation_loss_m: float = Field(
        default=0.0, ge=0, description="D- brut (somme naïve des altitudes GPX, avant correction)."
    )
    start_lat: float = Field(ge=-90, le=90)
    start_lon: float = Field(ge=-180, le=180)
    segments: list[ElevationSegment] = Field(default_factory=list)
    points: list[TrackPoint] = Field(
        default_factory=list,
        description="Points de tracé (lat/lon/altitude), source des enrichissements.",
    )


class RaceContext(_Frozen):
    """Contexte de la course saisi par le coureur (alimente la météo jour J)."""

    race_datetime: datetime = Field(description="Date et heure prévues de la course.")


class AthleteProfile(_Frozen):
    """Forme de l'athlète issue de COROS. Champs optionnels (dégradation gracieuse)."""

    threshold_pace_sec_per_km: float | None = Field(default=None, gt=0)
    vo2max: float | None = Field(default=None, gt=0)
    resting_hr: int | None = Field(default=None, gt=0)
    recovery_pct: float | None = Field(default=None, ge=0, le=100)
    recovery_status: str | None = Field(default=None, description="Niveau de récupération (texte).")
    weight_kg: float | None = Field(default=None, gt=0, description="Poids (grade-adjusted pace).")


class ActivitySummary(_Frozen):
    """Résumé d'une course passée (COROS `querySportRecords`).

    Brique de la **calibration** (#76) : on agrège ces résumés pour personnaliser la baseline.
    `start_timestamp` (epoch s) sert de curseur d'ingestion incrémentale. `elevation_gain_m`
    n'est pas fourni par le résumé COROS (rempli plus tard via les flux d'activité, axe D).
    """

    label_id: str = Field(description="Identifiant COROS de l'activité (clé d'unicité).")
    sport_type: int = Field(description="Code sport COROS (100 = outdoor run, 102 = trail).")
    start_timestamp: int = Field(gt=0, description="Début de l'activité (epoch secondes, UTC).")
    activity_date: date
    distance_km: float = Field(gt=0)
    duration_s: int = Field(gt=0)
    avg_pace_sec_per_km: float | None = Field(default=None, gt=0)
    avg_hr: int | None = Field(default=None, gt=0)
    start_lat: float | None = Field(default=None, ge=-90, le=90)
    start_lon: float | None = Field(default=None, ge=-180, le=180)
    location: str | None = None
    elevation_gain_m: float | None = Field(default=None, ge=0)
    weather_temperature_c: float | None = Field(
        default=None, description="Température ERA5 jointe (axe B), remplie après ingestion météo."
    )


class CalibrationProfile(_Frozen):
    """Personnalisation dérivée de l'historique COROS (#76), tous champs optionnels.

    Consolide jusqu'à 4 axes. Le seuil COROS reste l'ancre : on **ne** stocke pas une allure
    de remplacement, mais des facteurs qui ajustent la baseline. Tant qu'un axe manque de
    données, son champ reste `None` → la baseline retombe sur ses constantes génériques.
    """

    computed_at: datetime | None = None
    sample_count: int = Field(default=0, ge=0, description="Nb de courses ayant nourri le calcul.")
    # Axe A — décroissance allure↔distance (remplace les facteurs littéraires) & relation FC↔allure.
    distance_factors: list[tuple[float, float]] | None = Field(
        default=None, description="Paliers (distance_max_km, facteur) calibrés sur efforts réels."
    )
    hr_pace_slope: float | None = None
    # Axe B — sensibilité chaleur personnelle.
    heat_coeff_per_deg: float | None = Field(default=None, ge=0)
    heat_threshold_c: float | None = None
    # Axe C — tendance de forme.
    fitness_trend: float | None = None
    # Axe D — courbe allure-pente personnelle.
    grade_curve: list[float] | None = None


class YearlyWeather(_Frozen):
    """Relevés météo d'une année passée à une date donnée (ERA5)."""

    year: int
    temperature_c: float | None = None
    precipitation_mm: float | None = None
    wind_speed_kmh: float | None = None


class WeatherContext(_Frozen):
    """Conditions au point de départ pour la date/heure de course (optionnel).

    Selon l'horizon, `source` vaut `forecast` (prévision réelle, ≤16 j) ou `last_year`
    (relevés de l'an dernier, course encore trop lointaine). `history` donne les relevés des
    dernières années à la même date. `horizon_days` = nombre de jours jusqu'à la course.
    """

    source: WeatherSource | None = None
    horizon_days: int | None = None
    weather_code: int | None = Field(default=None, description="Code météo WMO (prévision).")
    temperature_c: float | None = None
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    wind_speed_kmh: float | None = Field(default=None, ge=0)
    precipitation_mm: float | None = Field(default=None, ge=0)
    air_quality_index: float | None = Field(default=None, ge=0)
    history: list[YearlyWeather] = Field(
        default_factory=list, description="Relevés des dernières années à la même date."
    )


class SurfaceContext(_Frozen):
    """Type de surface du parcours (OSM/Overpass). Optionnel."""

    primary_surface: str | None = None
    surface_breakdown: dict[str, float] | None = Field(
        default=None, description="Répartition des surfaces (proportion par type)."
    )


class KmPlan(_Frozen):
    """Recommandation d'allure pour un kilomètre."""

    km_index: int = Field(ge=1)
    target_pace_sec_per_km: float = Field(gt=0)
    effort: str = Field(description="Intensité conseillée (ex. easy / steady / hard).")
    gradient_pct: float
    note: str | None = None


class CourseSection(_Frozen):
    """Tranche homogène du parcours (km consécutifs de même effort) — découpage déterministe."""

    start_km: int = Field(ge=1)
    end_km: int = Field(ge=1)
    effort: str = Field(description="Intensité dominante (easy / steady / hard).")
    avg_gradient_pct: float


class SectionNote(_Frozen):
    """Consigne de coaching en langage naturel pour une tranche (narratif LLM, bornes figées)."""

    start_km: int = Field(ge=1)
    end_km: int = Field(ge=1)
    note: str


class PaceStrategy(_Frozen):
    """Stratégie d'allure complète renvoyée au coureur."""

    distance_km: float = Field(gt=0)
    estimated_time_sec: float = Field(gt=0)
    average_pace_sec_per_km: float = Field(gt=0)
    km_plans: list[KmPlan] = Field(min_length=1)
    summary: str | None = None
    generated_by: str = Field(description="Origine de la stratégie : « llm » ou « baseline ».")
    section_narrative: list[SectionNote] = Field(
        default_factory=list,
        description="Narratif de course par tranche (assemblé serveur ; bornes déterministes).",
    )


class RoutePoint(_Frozen):
    """Coordonnée du tracé (échantillonné) pour l'affichage cartographique."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class CourseSummary(_Frozen):
    """Résumé du parcours pour la réponse API (tracé échantillonné, sans tous les points)."""

    distance_km: float = Field(gt=0)
    elevation_gain_m: float = Field(ge=0)
    elevation_loss_m: float = Field(ge=0)
    elevation_source: ElevationSource = "gpx"
    raw_elevation_gain_m: float = Field(default=0.0, ge=0)
    raw_elevation_loss_m: float = Field(default=0.0, ge=0)
    start_lat: float
    start_lon: float
    segments: list[ElevationSegment] = Field(default_factory=list)
    route: list[RoutePoint] = Field(default_factory=list)


class StrategyResponse(_Frozen):
    """Réponse enrichie de `POST /strategy` : stratégie + données qui l'ont nourrie."""

    strategy: PaceStrategy
    course: CourseSummary
    athlete: AthleteProfile | None = None
    weather: WeatherContext | None = None


class ComparedStrategy(_Frozen):
    """Une variante (moteur × prompt) de la comparaison (cf. #74)."""

    label: str = Field(description="Libellé affiché, ex. « qwen2.5:14b · CoT ».")
    model: str = Field(description="Identifiant du modèle, ex. « qwen2.5:14b ».")
    mode: GenerationMode = Field(description="Mode de génération (autonomous / cot).")
    strategy: PaceStrategy | None = None
    error: str | None = Field(default=None, description="Message si la génération a échoué.")


class StrategyComparison(_Frozen):
    """Réponse de `POST /strategy/compare` : baseline + N variantes LLM brutes (cf. #74).

    `baseline` est la référence déterministe ; `variants` sont les stratégies **brutes**
    (sans garde-fou ni repli) de chaque couple moteur × prompt comparé.
    """

    course: CourseSummary
    athlete: AthleteProfile | None = None
    weather: WeatherContext | None = None
    baseline: PaceStrategy
    recommended: PaceStrategy
    variants: list[ComparedStrategy] = Field(default_factory=list)
