"""Lecture du journal des prédictions : historique paginé, détail, KPIs agrégés.

`HistoryReader` est un port lu par l'API ; `SqlHistoryReader` interroge Neon,
`NullHistoryReader` renvoie du vide quand la base n'est pas configurée.
"""

from typing import Protocol

from sqlalchemy import func, select
from sqlmodel import col

from app.db.engine import session_factory
from app.db.models import PredictionRun
from app.db.read_models import RunDetail, RunStats, RunSummary


class HistoryReader(Protocol):
    async def list_runs(self, *, limit: int, offset: int) -> list[RunSummary]: ...
    async def get_run(self, run_id: int) -> RunDetail | None: ...
    async def compute_stats(self) -> RunStats: ...


def _summary(run: PredictionRun) -> RunSummary:
    assert run.id is not None
    return RunSummary(
        id=run.id,
        created_at=run.created_at,
        distance_km=run.distance_km,
        race_datetime=run.race_datetime,
        generated_by=run.generated_by,
        average_pace_sec_per_km=run.strategy.get("average_pace_sec_per_km"),
        guardrails_passed=run.guardrails_passed,
        deviation_vs_baseline_pct=run.deviation_vs_baseline_pct,
        latency_ms=run.latency_ms,
    )


def _detail(run: PredictionRun) -> RunDetail:
    return RunDetail(
        **_summary(run).model_dump(),
        gpx_hash=run.gpx_hash,
        elevation_gain_m=run.elevation_gain_m,
        elevation_loss_m=run.elevation_loss_m,
        start_lat=run.start_lat,
        start_lon=run.start_lon,
        athlete=run.athlete,
        weather=run.weather,
        surface=run.surface,
        strategy=run.strategy,
    )


class SqlHistoryReader:
    async def list_runs(self, *, limit: int, offset: int) -> list[RunSummary]:
        async with session_factory()() as session:
            result = await session.execute(
                select(PredictionRun)
                .order_by(col(PredictionRun.id).desc())
                .limit(limit)
                .offset(offset)
            )
            return [_summary(run) for run in result.scalars().all()]

    async def get_run(self, run_id: int) -> RunDetail | None:
        async with session_factory()() as session:
            run = await session.get(PredictionRun, run_id)
            return _detail(run) if run is not None else None

    async def compute_stats(self) -> RunStats:
        async with session_factory()() as session:
            row = (
                await session.execute(
                    select(
                        func.count(),
                        func.count().filter(col(PredictionRun.generated_by) == "llm"),
                        func.count().filter(col(PredictionRun.guardrails_passed)),
                        func.avg(PredictionRun.deviation_vs_baseline_pct),
                        func.avg(PredictionRun.latency_ms),
                    )
                )
            ).one()
        total, llm, guarded, avg_dev, avg_lat = row
        return _to_stats(total, llm, guarded, avg_dev, avg_lat)


class NullHistoryReader:
    async def list_runs(self, *, limit: int, offset: int) -> list[RunSummary]:
        return []

    async def get_run(self, run_id: int) -> RunDetail | None:
        return None

    async def compute_stats(self) -> RunStats:
        return _to_stats(0, 0, 0, None, None)


def _pct(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _to_stats(
    total: int, llm: int, guarded: int, avg_dev: float | None, avg_lat: float | None
) -> RunStats:
    return RunStats(
        total_runs=total,
        llm_runs=llm,
        baseline_runs=total - llm,
        llm_share_pct=_pct(llm, total),
        guardrails_passed_pct=_pct(guarded, total),
        avg_deviation_vs_baseline_pct=round(avg_dev, 1) if avg_dev is not None else None,
        avg_latency_ms=round(avg_lat, 1) if avg_lat is not None else None,
    )
