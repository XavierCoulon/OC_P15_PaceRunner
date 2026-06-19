"""Tests de la stratégie baseline déterministe."""

from app.domain.models import AthleteProfile, CourseProfile, ElevationSegment
from app.services.baseline_strategy import build_baseline_strategy


def _course(gradients: list[float]) -> CourseProfile:
    segments = [
        ElevationSegment(
            km_index=i + 1,
            distance_km=1.0,
            elevation_gain_m=max(g, 0.0),
            elevation_loss_m=max(-g, 0.0),
            gradient_pct=g,
        )
        for i, g in enumerate(gradients)
    ]
    return CourseProfile(
        distance_km=float(len(gradients)),
        elevation_gain_m=sum(max(g, 0.0) for g in gradients),
        elevation_loss_m=sum(max(-g, 0.0) for g in gradients),
        start_lat=43.0,
        start_lon=-1.0,
        segments=segments,
    )


def _athlete(threshold: float | None = 300.0, recovery: float | None = 100.0) -> AthleteProfile:
    return AthleteProfile(threshold_pace_sec_per_km=threshold, recovery_pct=recovery)


def test_flat_course_uniform_pace() -> None:
    strategy = build_baseline_strategy(_course([0.0, 0.0, 0.0]), _athlete())
    assert strategy.generated_by == "baseline"
    assert len(strategy.km_plans) == 3
    paces = {p.target_pace_sec_per_km for p in strategy.km_plans}
    assert len(paces) == 1  # toutes égales
    assert all(p.effort == "steady" for p in strategy.km_plans)


def test_grade_orders_paces_and_efforts() -> None:
    strategy = build_baseline_strategy(_course([0.0, 5.0, -5.0]), _athlete())
    flat, uphill, downhill = strategy.km_plans
    assert (
        uphill.target_pace_sec_per_km
        > flat.target_pace_sec_per_km
        > downhill.target_pace_sec_per_km
    )
    assert uphill.effort == "hard"
    assert flat.effort == "steady"
    assert downhill.effort == "easy"


def test_lower_recovery_is_slower() -> None:
    course = _course([0.0, 0.0])
    fresh = build_baseline_strategy(course, _athlete(recovery=95.0))
    tired = build_baseline_strategy(course, _athlete(recovery=50.0))
    assert tired.average_pace_sec_per_km > fresh.average_pace_sec_per_km


def test_estimated_time_matches_paces() -> None:
    strategy = build_baseline_strategy(_course([0.0, 2.0]), _athlete())
    expected = sum(p.target_pace_sec_per_km for p in strategy.km_plans)  # 1 km par segment
    assert strategy.estimated_time_sec == round(expected, 1)


def test_without_athlete_uses_fallback_pace() -> None:
    strategy = build_baseline_strategy(_course([0.0, 1.0]), None)
    assert strategy.generated_by == "baseline"
    assert strategy.average_pace_sec_per_km > 0
    assert len(strategy.km_plans) == 2
