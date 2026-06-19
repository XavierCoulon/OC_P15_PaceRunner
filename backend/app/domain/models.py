"""Modèles de domaine (contrats Pydantic).

Ce sont les objets de valeur échangés dans le pipeline d'orchestration : profil de
parcours issu du GPX, contexte de course, enrichissements (athlète, météo, surface)
et stratégie d'allure produite. Tous immuables (`frozen=True`).

Conventions :
- allures exprimées en **secondes par kilomètre** (`*_sec_per_km`) — numérique, facile à calculer ;
- durées en **secondes** ; distances en **kilomètres** ; dénivelés en **mètres** ; pentes en **%**.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class CourseProfile(_Frozen):
    """Profil de parcours dérivé du fichier GPX (après nettoyage des altitudes)."""

    distance_km: float = Field(gt=0)
    elevation_gain_m: float = Field(ge=0, description="Dénivelé positif total (D+).")
    elevation_loss_m: float = Field(ge=0, description="Dénivelé négatif total (D-).")
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
    goal: str | None = Field(
        default=None,
        description="Objectif libre (ex. « finir », allure cible, temps visé).",
    )


class AthleteProfile(_Frozen):
    """Forme de l'athlète issue de COROS. Champs optionnels (dégradation gracieuse)."""

    threshold_pace_sec_per_km: float | None = Field(default=None, gt=0)
    vo2max: float | None = Field(default=None, gt=0)
    resting_hr: int | None = Field(default=None, gt=0)
    recovery_pct: float | None = Field(default=None, ge=0, le=100)
    recovery_status: str | None = Field(default=None, description="Niveau de récupération (texte).")
    weight_kg: float | None = Field(default=None, gt=0, description="Poids (grade-adjusted pace).")


class WeatherContext(_Frozen):
    """Conditions prévues au point de départ pour la date/heure de course (optionnel)."""

    temperature_c: float | None = None
    wind_speed_kmh: float | None = Field(default=None, ge=0)
    precipitation_mm: float | None = Field(default=None, ge=0)
    air_quality_index: float | None = Field(default=None, ge=0)


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


class PaceStrategy(_Frozen):
    """Stratégie d'allure complète renvoyée au coureur."""

    distance_km: float = Field(gt=0)
    estimated_time_sec: float = Field(gt=0)
    average_pace_sec_per_km: float = Field(gt=0)
    km_plans: list[KmPlan] = Field(min_length=1)
    summary: str | None = None
    generated_by: str = Field(description="Origine de la stratégie : « llm » ou « baseline ».")
