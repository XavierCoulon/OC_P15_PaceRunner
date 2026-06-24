"""Tests des métriques et du runner d'évaluation (sans LLM réel)."""

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
from app.evaluation.runner import run_evaluation
from app.services.strategy_metrics import deviation_vs_baseline_pct, guardrails_passed


def _strategy(avg: float, generated_by: str = "llm") -> PaceStrategy:
    return PaceStrategy(
        distance_km=2.0,
        estimated_time_sec=avg * 2,
        average_pace_sec_per_km=avg,
        km_plans=[
            KmPlan(km_index=1, target_pace_sec_per_km=avg, effort="steady", gradient_pct=0.0)
        ],
        generated_by=generated_by,
    )


def _course() -> CourseProfile:
    return CourseProfile(
        distance_km=1.0,
        elevation_gain_m=0.0,
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
            )
        ],
    )


def test_deviation_vs_baseline_pct() -> None:
    assert deviation_vs_baseline_pct(_strategy(330.0), _strategy(300.0)) == 10.0
    assert deviation_vs_baseline_pct(_strategy(270.0), _strategy(300.0)) == -10.0


def test_guardrails_passed_wrapper() -> None:
    course = _course()
    assert guardrails_passed(_strategy(300.0), course, None) is True
    assert guardrails_passed(_strategy(60.0), course, None) is False  # hors bornes absolues


class _FakeGenerator:
    """Renvoie une stratégie valide alignée sur le parcours (un km_plan par segment)."""

    async def generate(
        self,
        course: CourseProfile,
        race: RaceContext,
        athlete: AthleteProfile | None,
        weather: WeatherContext | None,
        surface: SurfaceContext | None,
        baseline: PaceStrategy | None = None,
        autonomous: bool = False,
    ) -> PaceStrategy:
        plans = [
            KmPlan(
                km_index=s.km_index,
                target_pace_sec_per_km=300 + s.gradient_pct * 4,
                effort="steady",
                gradient_pct=s.gradient_pct,
            )
            for s in course.segments
        ]
        return PaceStrategy(
            distance_km=course.distance_km,
            estimated_time_sec=1.0,
            average_pace_sec_per_km=300.0,
            km_plans=plans,
            generated_by="llm",
        )


class _FailingGenerator:
    async def generate(self, *args: object, **kwargs: object) -> PaceStrategy:
        raise RuntimeError("LLM KO")


async def test_run_evaluation_with_valid_generator() -> None:
    rows = await run_evaluation(_FakeGenerator())
    assert len(rows) == 4  # plat / vallonné / long / pentes extrêmes
    assert all(r.generated_by == "llm" for r in rows)
    assert all(r.deviation_pct is not None for r in rows)


async def test_run_evaluation_marks_generator_failures() -> None:
    rows = await run_evaluation(_FailingGenerator())
    assert all(r.generated_by == "error" for r in rows)
    assert all(not r.guardrails_passed for r in rows)
    assert all(r.llm_pace is None for r in rows)
