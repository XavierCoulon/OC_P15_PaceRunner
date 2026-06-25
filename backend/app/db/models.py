"""Modèles de persistance (SQLModel) — journal des prédictions.

`prediction_runs` enregistre chaque génération de stratégie : entrée (hash GPX, profil,
contexte de course), enrichissements (snapshots athlète/météo/surface en JSONB), stratégie
produite (JSONB), provenance et métriques qualité (latence, garde-fous, écart baseline).
"""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Horodatage UTC naïf (stocké en TIMESTAMP sans fuseau)."""
    return datetime.now(UTC).replace(tzinfo=None)


class PredictionRun(SQLModel, table=True):
    __tablename__ = "prediction_runs"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)

    # Entrée
    gpx_hash: str = Field(index=True)
    distance_km: float
    elevation_gain_m: float
    elevation_loss_m: float
    race_datetime: datetime
    start_lat: float
    start_lon: float

    # Enrichissements (snapshots)
    athlete: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    weather: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    surface: dict[str, Any] | None = Field(default=None, sa_type=JSONB)

    # Sortie
    strategy: dict[str, Any] = Field(sa_type=JSONB)
    generated_by: str = Field(index=True)
    model: str | None = None
    provider: str | None = None

    # Métriques / qualité
    latency_ms: float | None = None
    guardrails_passed: bool = False
    deviation_vs_baseline_pct: float | None = None
    calibration_used: bool = Field(default=False, index=True)
    error: str | None = None


class CorosActivity(SQLModel, table=True):
    """Résumé d'une course COROS persisté (source de la calibration, #76).

    `label_id` est la clé d'unicité (upsert idempotent). `streams_fetched` indique si les flux
    détaillés (axe D) ont déjà été récupérés. Les colonnes météo sont jointes ultérieurement
    (axe B). Aucun flux haute résolution n'est stocké ici.
    """

    __tablename__ = "coros_activities"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)

    label_id: str = Field(index=True, unique=True)
    sport_type: int
    start_timestamp: int = Field(index=True)
    activity_date: date
    distance_km: float
    duration_s: int
    avg_pace_sec_per_km: float | None = None
    avg_hr: int | None = None
    start_lat: float | None = None
    start_lon: float | None = None
    location: str | None = None
    elevation_gain_m: float | None = None

    # Flux détaillés (axe D) — réservé : jamais renseigné à ce jour (axe D reporté, #80).
    streams_fetched: bool = Field(default=False)
    # Météo historique jointe (axe B) — remplie lors de l'ingestion météo.
    weather_temperature_c: float | None = None


class CalibrationSnapshot(SQLModel, table=True):
    """Dernier `CalibrationProfile` calculé (lu sur le chemin /strategy, jamais refetché)."""

    __tablename__ = "calibration_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    computed_at: datetime = Field(default_factory=_utcnow, index=True)
    sample_count: int = 0
    profile: dict[str, Any] = Field(sa_type=JSONB)
