"""Tests des garde-fous métier sur la stratégie."""

from app.domain.models import AthleteProfile, CourseProfile, ElevationSegment, KmPlan, PaceStrategy
from app.services.strategy_guardrails import check_strategy


def _course(gradients: list[float]) -> CourseProfile:
    return CourseProfile(
        distance_km=float(len(gradients)),
        elevation_gain_m=0.0,
        elevation_loss_m=0.0,
        start_lat=43.0,
        start_lon=-1.0,
        segments=[
            ElevationSegment(
                km_index=i + 1,
                distance_km=1.0,
                elevation_gain_m=0.0,
                elevation_loss_m=0.0,
                gradient_pct=g,
            )
            for i, g in enumerate(gradients)
        ],
    )


def _strategy(paces: list[tuple[float, float]]) -> PaceStrategy:
    # paces : liste de (allure, pente)
    plans = [
        KmPlan(km_index=i + 1, target_pace_sec_per_km=p, effort="steady", gradient_pct=g)
        for i, (p, g) in enumerate(paces)
    ]
    return PaceStrategy(
        distance_km=float(len(paces)),
        estimated_time_sec=sum(p for p, _ in paces),
        average_pace_sec_per_km=sum(p for p, _ in paces) / len(paces),
        km_plans=plans,
        generated_by="llm",
    )


_ATHLETE = AthleteProfile(threshold_pace_sec_per_km=300.0)


def test_valid_strategy_has_no_violations() -> None:
    course = _course([0.0, 5.0, -5.0])
    strategy = _strategy([(300.0, 0.0), (350.0, 5.0), (270.0, -5.0)])
    assert check_strategy(strategy, course, _ATHLETE) == []


def test_pace_out_of_absolute_bounds() -> None:
    course = _course([0.0])
    strategy = _strategy([(60.0, 0.0)])  # 1:00/km impossible
    assert any("absolues" in r for r in check_strategy(strategy, course, _ATHLETE))


def test_pace_incoherent_with_threshold() -> None:
    course = _course([0.0])
    # 170 s/km < borne basse relative (0.6 × seuil 300 = 180) → incohérent.
    strategy = _strategy([(170.0, 0.0)])
    assert any("seuil" in r for r in check_strategy(strategy, course, _ATHLETE))


def test_uphill_not_slower_than_downhill() -> None:
    course = _course([5.0, -5.0])
    strategy = _strategy([(280.0, 5.0), (320.0, -5.0)])  # montée plus rapide que descente
    assert any("incohérent" in r for r in check_strategy(strategy, course, _ATHLETE))


def test_km_count_mismatch() -> None:
    course = _course([0.0, 0.0, 0.0])
    strategy = _strategy([(300.0, 0.0)])
    assert any("nombre de km" in r for r in check_strategy(strategy, course, _ATHLETE))


def test_pace_too_far_from_grade_adjusted_baseline() -> None:
    # Grosse montée (+10%) mais allure « plate » → ignore la pente → écart à la baseline.
    course = _course([10.0])
    strategy = _strategy([(300.0, 10.0)])
    assert any("baseline" in r for r in check_strategy(strategy, course, _ATHLETE))
