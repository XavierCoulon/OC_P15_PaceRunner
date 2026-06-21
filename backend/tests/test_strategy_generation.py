"""Tests de l'orchestration génération + fallback (G2)."""

from datetime import datetime

from app.domain.models import (
    AthleteProfile,
    CourseProfile,
    ElevationSegment,
    KmPlan,
    PaceStrategy,
    RaceContext,
    SurfaceContext,
    WeatherContext,
)
from app.services.strategy_generation import generate_strategy


def _course() -> CourseProfile:
    return CourseProfile(
        distance_km=2.0,
        elevation_gain_m=10.0,
        elevation_loss_m=0.0,
        start_lat=43.0,
        start_lon=-1.0,
        segments=[
            ElevationSegment(
                km_index=1,
                distance_km=1.0,
                elevation_gain_m=0,
                elevation_loss_m=0,
                gradient_pct=0.0,
            ),
            ElevationSegment(
                km_index=2,
                distance_km=1.0,
                elevation_gain_m=10,
                elevation_loss_m=0,
                gradient_pct=5.0,
            ),
        ],
    )


_RACE = RaceContext(race_datetime=datetime(2026, 9, 1, 9, 0))
_ATHLETE = AthleteProfile(threshold_pace_sec_per_km=300.0)


def _strategy(paces: list[tuple[float, float]], *, estimated: float = 9999.0) -> PaceStrategy:
    plans = [
        KmPlan(km_index=i + 1, target_pace_sec_per_km=p, effort="steady", gradient_pct=g)
        for i, (p, g) in enumerate(paces)
    ]
    return PaceStrategy(
        distance_km=2.0,
        estimated_time_sec=estimated,
        average_pace_sec_per_km=estimated / 2.0,
        km_plans=plans,
        generated_by="llm",
    )


class _FakeGenerator:
    def __init__(self, strategy: PaceStrategy | None = None, exc: Exception | None = None) -> None:
        self._strategy = strategy
        self._exc = exc

    async def generate(
        self,
        course: CourseProfile,
        race: RaceContext,
        athlete: AthleteProfile | None,
        weather: WeatherContext | None,
        surface: SurfaceContext | None,
    ) -> PaceStrategy:
        if self._exc is not None:
            raise self._exc
        assert self._strategy is not None
        return self._strategy


async def test_valid_llm_strategy_is_kept_and_totals_recomputed() -> None:
    generator = _FakeGenerator(_strategy([(300.0, 0.0), (330.0, 5.0)], estimated=9999.0))
    outcome = await generate_strategy(generator, _course(), _RACE, _ATHLETE, None, None)
    assert outcome.strategy.generated_by == "llm"
    assert outcome.strategy.estimated_time_sec == 630.0  # 300*1 + 330*1, recalculé (pas 9999)
    assert outcome.strategy.average_pace_sec_per_km == 315.0
    assert outcome.quality.llm_guardrails_passed is True
    # Effort recalculé serveur depuis la pente : km2 (+5%) → hard.
    assert outcome.strategy.km_plans[1].effort == "hard"


async def test_aberrant_strategy_falls_back_to_baseline() -> None:
    generator = _FakeGenerator(_strategy([(60.0, 0.0), (60.0, 5.0)]))  # allures impossibles
    outcome = await generate_strategy(generator, _course(), _RACE, _ATHLETE, None, None)
    assert outcome.strategy.generated_by == "baseline"
    assert outcome.quality.llm_guardrails_passed is False


async def test_generator_failure_falls_back_to_baseline() -> None:
    generator = _FakeGenerator(exc=RuntimeError("LLM down"))
    outcome = await generate_strategy(generator, _course(), _RACE, _ATHLETE, None, None)
    assert outcome.strategy.generated_by == "baseline"
