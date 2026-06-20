"""Tests du PredictionRepository : mapping pur + journalisation non bloquante."""

from datetime import UTC, datetime

from app.adapters.prediction_repo import NullPredictionRepository, to_prediction_run
from app.domain.models import (
    AthleteProfile,
    CourseProfile,
    ElevationSegment,
    KmPlan,
    PaceStrategy,
    RaceContext,
)
from app.services.strategy_generation import GenerationOutcome
from app.services.strategy_quality import compute_quality
from app.services.strategy_service import _journal


def _course() -> CourseProfile:
    return CourseProfile(
        distance_km=2.0,
        elevation_gain_m=20.0,
        elevation_loss_m=5.0,
        start_lat=43.47,
        start_lon=-1.48,
        segments=[
            ElevationSegment(
                km_index=1,
                distance_km=1.0,
                elevation_gain_m=0,
                elevation_loss_m=0,
                gradient_pct=0.0,
            )
        ],
    )


def _strategy() -> PaceStrategy:
    return PaceStrategy(
        distance_km=2.0,
        estimated_time_sec=600.0,
        average_pace_sec_per_km=300.0,
        km_plans=[
            KmPlan(km_index=1, target_pace_sec_per_km=300, effort="steady", gradient_pct=0.0)
        ],
        generated_by="llm",
    )


def test_to_prediction_run_maps_fields() -> None:
    run = to_prediction_run(
        gpx_hash="abc123",
        course=_course(),
        race=RaceContext(race_datetime=datetime(2026, 9, 1, 9, 0, tzinfo=UTC)),
        athlete=AthleteProfile(threshold_pace_sec_per_km=292.0),
        weather=None,
        surface=None,
        strategy=_strategy(),
        latency_ms=1500.0,
        guardrails_passed=True,
        deviation_vs_baseline_pct=-3.2,
    )
    assert run.gpx_hash == "abc123"
    assert run.distance_km == 2.0
    assert run.start_lat == 43.47
    assert run.generated_by == "llm"
    assert run.athlete is not None and run.athlete["threshold_pace_sec_per_km"] == 292.0
    assert run.strategy["generated_by"] == "llm"
    assert run.race_datetime.tzinfo is None  # stocké en UTC naïf
    assert run.guardrails_passed is True
    assert run.deviation_vs_baseline_pct == -3.2


async def test_null_repository_is_noop() -> None:
    await NullPredictionRepository().save_run(
        gpx_hash="x",
        course=_course(),
        race=RaceContext(race_datetime=datetime(2026, 9, 1, 9, 0)),
        athlete=None,
        weather=None,
        surface=None,
        strategy=_strategy(),
        latency_ms=1.0,
        guardrails_passed=False,
        deviation_vs_baseline_pct=0.0,
    )  # ne lève pas


class _FailingRepository:
    async def save_run(self, **kwargs: object) -> None:
        raise RuntimeError("DB down")


async def test_journal_swallows_repository_errors() -> None:
    course = _course()
    outcome = GenerationOutcome(
        strategy=_strategy(),
        quality=compute_quality(
            _strategy(), _strategy(), llm_guardrails_passed=True, latency_ms=1.0
        ),
    )
    # Ne doit pas lever malgré l'échec du repository.
    await _journal(
        _FailingRepository(),
        "hash",
        course,
        RaceContext(race_datetime=datetime(2026, 9, 1, 9, 0)),
        None,
        None,
        None,
        outcome,
    )
