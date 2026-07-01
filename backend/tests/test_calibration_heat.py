"""Tests de l'axe B (sensibilité chaleur) : calcul du coefficient + branchement baseline."""

from datetime import date, timedelta

from app.domain.models import (
    ActivitySummary,
    AthleteProfile,
    CalibrationProfile,
    CourseProfile,
    ElevationSegment,
    WeatherContext,
)
from app.services.baseline_strategy import build_baseline_strategy
from app.services.calibration_compute import calibration_note, compute_calibration

_TODAY = date(2026, 6, 24)
_THRESHOLD = 300.0


def _act(label: str, *, pace: float, temp: float | None, days_ago: int) -> ActivitySummary:
    return ActivitySummary(
        label_id=label,
        sport_type=100,
        start_timestamp=1_700_000_000 + days_ago,
        activity_date=_TODAY - timedelta(days=days_ago),
        distance_km=10.0,
        duration_s=int(pace * 10),
        avg_pace_sec_per_km=pace,
        weather_temperature_c=temp,
    )


def _hot_dataset() -> list[ActivitySummary]:
    """Courses ~10 km : à 10 °C allure ≈ seuil ; au-delà de 20 °C, ralentissement net."""
    activities: list[ActivitySummary] = []
    # Jours frais (≤ 20 °C) : allure proche du seuil.
    for i, temp in enumerate([8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]):
        activities.append(_act(f"cool{i}", pace=300.0, temp=temp, days_ago=i * 2))
    # Jours chauds : +3 s/km par °C au-dessus de 20 (≈ +1 %/°C sur 300 s).
    for i, temp in enumerate([22.0, 24.0, 26.0, 28.0, 30.0, 25.0, 27.0, 29.0, 31.0, 23.0]):
        activities.append(_act(f"hot{i}", pace=300 + (temp - 20) * 3.0, temp=temp, days_ago=20 + i))
    return activities


def test_heat_coeff_learned_from_hot_days() -> None:
    profile = compute_calibration(_hot_dataset(), _THRESHOLD, today=_TODAY)
    assert profile.heat_coeff_per_deg is not None
    assert profile.heat_threshold_c == 20.0
    # Pente attendue ≈ 3 s/km / 300 s = 0,01 /°C.
    assert 0.007 <= profile.heat_coeff_per_deg <= 0.013


def test_no_heat_coeff_without_hot_days() -> None:
    cool = [_act(f"c{i}", pace=300.0, temp=12.0, days_ago=i) for i in range(12)]
    profile = compute_calibration(cool, _THRESHOLD, today=_TODAY)
    assert profile.heat_coeff_per_deg is None


def test_no_heat_coeff_without_temperature() -> None:
    no_temp = [_act(f"n{i}", pace=300.0, temp=None, days_ago=i) for i in range(15)]
    profile = compute_calibration(no_temp, _THRESHOLD, today=_TODAY)
    assert profile.heat_coeff_per_deg is None


def test_note_mentions_heat_sensitivity() -> None:
    profile = compute_calibration(_hot_dataset(), _THRESHOLD, today=_TODAY)
    note = calibration_note(profile)
    assert note is not None
    assert "chaleur" in note


def _course() -> CourseProfile:
    segments = [
        ElevationSegment(
            km_index=i + 1,
            distance_km=1.0,
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
            gradient_pct=0.0,
        )
        for i in range(10)
    ]
    return CourseProfile(
        distance_km=10.0,
        elevation_gain_m=0.0,
        elevation_loss_m=0.0,
        start_lat=43.0,
        start_lon=-1.0,
        segments=segments,
    )


def test_baseline_uses_personal_heat_sensitivity() -> None:
    # Coureur très sensible (2 %/°C) vs générique (0,6 %/°C) → plus pénalisé à 30 °C.
    athlete = AthleteProfile(threshold_pace_sec_per_km=_THRESHOLD)
    hot = WeatherContext(temperature_c=30.0)
    sensitive = CalibrationProfile(heat_coeff_per_deg=0.02, heat_threshold_c=20.0)

    generic = build_baseline_strategy(_course(), athlete, hot)
    personal = build_baseline_strategy(_course(), athlete, hot, calibration=sensitive)
    assert personal.average_pace_sec_per_km > generic.average_pace_sec_per_km
