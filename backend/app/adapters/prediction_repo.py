"""PredictionRepository : journalise les runs en base (SQLModel/asyncpg) ou non (no-op).

Le mapping domaine → `PredictionRun` est une fonction pure (testable sans base).
"""

from app.db.engine import session_factory
from app.db.models import PredictionRun
from app.domain.models import (
    AthleteProfile,
    CourseProfile,
    PaceStrategy,
    RaceContext,
    SurfaceContext,
    WeatherContext,
)


def to_prediction_run(
    *,
    gpx_hash: str,
    course: CourseProfile,
    race: RaceContext,
    athlete: AthleteProfile | None,
    weather: WeatherContext | None,
    surface: SurfaceContext | None,
    strategy: PaceStrategy,
    latency_ms: float,
    guardrails_passed: bool,
    deviation_vs_baseline_pct: float,
) -> PredictionRun:
    """Construit la ligne de journal à partir des données du pipeline."""
    race_dt = race.race_datetime.replace(tzinfo=None)
    return PredictionRun(
        gpx_hash=gpx_hash,
        distance_km=course.distance_km,
        elevation_gain_m=course.elevation_gain_m,
        elevation_loss_m=course.elevation_loss_m,
        race_datetime=race_dt,
        start_lat=course.start_lat,
        start_lon=course.start_lon,
        athlete=athlete.model_dump() if athlete is not None else None,
        weather=weather.model_dump() if weather is not None else None,
        surface=surface.model_dump() if surface is not None else None,
        strategy=strategy.model_dump(),
        generated_by=strategy.generated_by,
        latency_ms=latency_ms,
        guardrails_passed=guardrails_passed,
        deviation_vs_baseline_pct=deviation_vs_baseline_pct,
    )


class SqlPredictionRepository:
    """Implémente `PredictionRepository` en écrivant dans Neon."""

    async def save_run(
        self,
        *,
        gpx_hash: str,
        course: CourseProfile,
        race: RaceContext,
        athlete: AthleteProfile | None,
        weather: WeatherContext | None,
        surface: SurfaceContext | None,
        strategy: PaceStrategy,
        latency_ms: float,
        guardrails_passed: bool,
        deviation_vs_baseline_pct: float,
    ) -> None:
        run = to_prediction_run(
            gpx_hash=gpx_hash,
            course=course,
            race=race,
            athlete=athlete,
            weather=weather,
            surface=surface,
            strategy=strategy,
            latency_ms=latency_ms,
            guardrails_passed=guardrails_passed,
            deviation_vs_baseline_pct=deviation_vs_baseline_pct,
        )
        async with session_factory()() as session:
            session.add(run)
            await session.commit()


class NullPredictionRepository:
    """Implémente `PredictionRepository` sans rien persister (base non configurée / tests)."""

    async def save_run(self, **kwargs: object) -> None:
        return None
