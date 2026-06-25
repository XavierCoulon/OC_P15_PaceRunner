"""Modèles de lecture du journal (réponses des endpoints /history et /stats)."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.domain.models import CalibrationProfile


class RunSummary(BaseModel):
    """Ligne d'historique (vue liste)."""

    id: int
    created_at: datetime
    distance_km: float
    race_datetime: datetime
    generated_by: str
    average_pace_sec_per_km: float | None
    guardrails_passed: bool
    deviation_vs_baseline_pct: float | None
    latency_ms: float | None


class RunDetail(RunSummary):
    """Détail complet d'un run (snapshots + stratégie)."""

    gpx_hash: str
    elevation_gain_m: float
    elevation_loss_m: float
    start_lat: float
    start_lon: float
    athlete: dict[str, Any] | None
    weather: dict[str, Any] | None
    surface: dict[str, Any] | None
    strategy: dict[str, Any]


class RunStats(BaseModel):
    """KPIs agrégés du journal (monitoring, C5)."""

    total_runs: int
    llm_runs: int
    baseline_runs: int
    llm_share_pct: float
    guardrails_passed_pct: float
    avg_deviation_vs_baseline_pct: float | None
    avg_latency_ms: float | None


class CalibrationStatus(BaseModel):
    """État des données COROS en base (réponse de `GET /calibration`, bloc 1 du front)."""

    activity_count: int
    first_activity_date: date | None
    last_activity_date: date | None
    last_synced_at: datetime | None
    trail_sample_count: int
    calibration_computed_at: datetime | None
    calibration: CalibrationProfile | None = None


class CalibrationRefreshResult(BaseModel):
    """Réponse de `POST /calibration/refresh` : bilan d'ingestion + état résultant."""

    fetched: int
    inserted: int
    status: CalibrationStatus
