"""Tests du calcul pur de calibration (axes A & C) et de la note qualitative."""

from datetime import date, timedelta

from app.domain.models import (
    ActivitySummary,
    AthleteProfile,
    CalibrationProfile,
    CourseProfile,
    ElevationSegment,
)
from app.services.baseline_strategy import DISTANCE_BINS, build_baseline_strategy
from app.services.calibration_compute import calibration_note, compute_calibration

_TODAY = date(2026, 6, 24)


def _act(label: str, *, dist: float, pace: float | None, days_ago: int) -> ActivitySummary:
    return ActivitySummary(
        label_id=label,
        sport_type=100,
        start_timestamp=1_700_000_000 + days_ago,
        activity_date=_TODAY - timedelta(days=days_ago),
        distance_km=dist,
        duration_s=int((pace or 360) * dist),
        avg_pace_sec_per_km=pace,
    )


def _course(distance_km: float) -> CourseProfile:
    segments = [
        ElevationSegment(
            km_index=i + 1,
            distance_km=1.0,
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
            gradient_pct=0.0,
        )
        for i in range(int(distance_km))
    ]
    return CourseProfile(
        distance_km=distance_km,
        elevation_gain_m=0.0,
        elevation_loss_m=0.0,
        start_lat=43.0,
        start_lon=-1.0,
        segments=segments,
    )


def test_distance_factors_from_best_efforts() -> None:
    # 6 courses ~10 km, dont des efforts rapides (300) et des footings (400) → seuil 300.
    activities = [
        _act("f1", dist=9.5, pace=300.0, days_ago=10),
        _act("f2", dist=10.0, pace=305.0, days_ago=20),
        _act("s1", dist=9.0, pace=400.0, days_ago=30),
        _act("s2", dist=9.8, pace=410.0, days_ago=40),
        _act("s3", dist=10.0, pace=395.0, days_ago=50),
        _act("s4", dist=9.2, pace=420.0, days_ago=60),
    ]
    profile = compute_calibration(activities, threshold_pace_sec_per_km=300.0, today=_TODAY)
    assert profile.distance_factors is not None
    # La tranche ≤10 km est calibrée sur le meilleur effort (~300/300 = 1.0), pas la moyenne.
    bin_10 = next(f for up, f in profile.distance_factors if up == 10.0)
    assert 0.95 <= bin_10 <= 1.05
    # Les tranches sans données gardent le facteur générique (ex. semi).
    generic_half = next(f for up, f in DISTANCE_BINS if up == 21.1)
    cal_half = next(f for up, f in profile.distance_factors if up == 21.1)
    assert cal_half == generic_half


def test_distance_factors_are_monotonic() -> None:
    # Beaucoup de 10 km rapides (~280) mais aucun semi → le semi retombe sur générique (1.05),
    # qui ne doit PAS être plus rapide que le palier 10 km calibré (~0.93).
    activities = [_act(f"f{i}", dist=9.0 + i * 0.1, pace=280.0, days_ago=i * 2) for i in range(6)]
    profile = compute_calibration(activities, threshold_pace_sec_per_km=300.0, today=_TODAY)
    assert profile.distance_factors is not None
    factors = [f for _, f in profile.distance_factors]
    assert factors == sorted(factors)  # non décroissants : jamais plus rapide quand la distance ↑


def test_no_distance_factors_when_threshold_missing() -> None:
    activities = [_act("f1", dist=10.0, pace=300.0, days_ago=10)]
    profile = compute_calibration(activities, threshold_pace_sec_per_km=None, today=_TODAY)
    assert profile.distance_factors is None
    assert profile.sample_count == 1


def test_no_distance_factors_when_too_few_samples() -> None:
    activities = [_act("f1", dist=10.0, pace=300.0, days_ago=10)]
    profile = compute_calibration(activities, threshold_pace_sec_per_km=300.0, today=_TODAY)
    assert profile.distance_factors is None  # < min échantillons par tranche


def test_fitness_trend_detects_recent_load() -> None:
    # Charge soutenue sur 84 j, dont une pointe récente → ACWR ≥ 1.
    activities = [_act(f"r{i}", dist=10.0, pace=360.0, days_ago=i * 3) for i in range(28)]
    profile = compute_calibration(activities, threshold_pace_sec_per_km=300.0, today=_TODAY)
    assert profile.fitness_trend is not None
    assert profile.fitness_trend > 0


def test_calibration_note_qualitative() -> None:
    activities = [
        _act("f1", dist=9.5, pace=300.0, days_ago=5),
        _act("f2", dist=10.0, pace=305.0, days_ago=8),
        _act("f3", dist=9.8, pace=310.0, days_ago=12),
        _act("f4", dist=9.2, pace=315.0, days_ago=15),
    ]
    profile = compute_calibration(activities, threshold_pace_sec_per_km=300.0, today=_TODAY)
    note = calibration_note(profile)
    assert note is not None
    assert "meilleurs efforts" in note
    assert calibration_note(None) is None


def test_baseline_uses_calibrated_distance_factor() -> None:
    activities = [
        _act("f1", dist=9.5, pace=270.0, days_ago=5),
        _act("f2", dist=10.0, pace=275.0, days_ago=8),
        _act("f3", dist=9.8, pace=280.0, days_ago=12),
        _act("f4", dist=9.2, pace=285.0, days_ago=15),
    ]
    profile = compute_calibration(activities, threshold_pace_sec_per_km=300.0, today=_TODAY)
    course = _course(10.0)
    athlete = AthleteProfile(threshold_pace_sec_per_km=300.0)
    plain = build_baseline_strategy(course, athlete)
    calibrated = build_baseline_strategy(course, athlete, calibration=profile)
    # Meilleurs efforts ~270/300 = 0.9 < facteur générique 1.0 → baseline calibrée plus rapide.
    assert calibrated.average_pace_sec_per_km < plain.average_pace_sec_per_km


def test_baseline_falls_back_to_calibration_anchor_when_threshold_missing() -> None:
    # Allure seuil du jour indisponible (COROS flaky) → on reprend l'ancre de la calibration
    # (300 s) plutôt que le défaut générique (360 s) → baseline plus rapide et juste.
    course = _course(10.0)
    no_threshold = AthleteProfile()  # threshold_pace_sec_per_km = None
    cal = CalibrationProfile(anchor_pace_sec_per_km=300.0)
    with_anchor = build_baseline_strategy(course, no_threshold, calibration=cal)
    generic = build_baseline_strategy(course, no_threshold)
    assert with_anchor.average_pace_sec_per_km < generic.average_pace_sec_per_km
