"""Modèles de persistance (SQLModel) — journal des prédictions.

`prediction_runs` enregistre chaque génération de stratégie : entrée (hash GPX, profil,
contexte de course), enrichissements (snapshots athlète/météo/surface en JSONB), stratégie
produite (JSONB), provenance et métriques qualité (latence, garde-fous, écart baseline).
"""

from datetime import UTC, datetime
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
    error: str | None = None
