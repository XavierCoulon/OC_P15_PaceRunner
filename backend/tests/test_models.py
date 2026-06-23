"""Tests de validation des modèles de domaine."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.domain.models import (
    AthleteProfile,
    CourseProfile,
    ElevationSegment,
    KmPlan,
    PaceStrategy,
    RaceContext,
)


def _segment(km: int = 1) -> ElevationSegment:
    return ElevationSegment(
        km_index=km, distance_km=1.0, elevation_gain_m=10, elevation_loss_m=5, gradient_pct=1.0
    )


def test_course_profile_valid() -> None:
    profile = CourseProfile(
        distance_km=10.0,
        elevation_gain_m=120,
        elevation_loss_m=120,
        start_lat=45.5,
        start_lon=6.0,
        segments=[_segment(1), _segment(2)],
    )
    assert profile.distance_km == 10.0
    assert len(profile.segments) == 2


def test_course_profile_rejects_non_positive_distance() -> None:
    with pytest.raises(ValidationError):
        CourseProfile(
            distance_km=0, elevation_gain_m=0, elevation_loss_m=0, start_lat=0, start_lon=0
        )


def test_course_profile_rejects_out_of_range_coordinates() -> None:
    with pytest.raises(ValidationError):
        CourseProfile(
            distance_km=5, elevation_gain_m=0, elevation_loss_m=0, start_lat=120, start_lon=0
        )


def test_segment_rejects_zero_km_index() -> None:
    with pytest.raises(ValidationError):
        _segment(km=0)


def test_athlete_profile_all_optional() -> None:
    assert AthleteProfile().threshold_pace_sec_per_km is None


def test_athlete_profile_rejects_non_positive_vo2max() -> None:
    with pytest.raises(ValidationError):
        AthleteProfile(vo2max=0)


def test_pace_strategy_requires_at_least_one_km() -> None:
    with pytest.raises(ValidationError):
        PaceStrategy(
            distance_km=10,
            estimated_time_sec=3000,
            average_pace_sec_per_km=300,
            km_plans=[],
            generated_by="baseline",
        )


def test_pace_strategy_valid() -> None:
    strategy = PaceStrategy(
        distance_km=10,
        estimated_time_sec=3000,
        average_pace_sec_per_km=300,
        km_plans=[
            KmPlan(km_index=1, target_pace_sec_per_km=300, effort="steady", gradient_pct=0.0)
        ],
        generated_by="baseline",
    )
    assert strategy.km_plans[0].effort == "steady"


def test_models_are_frozen() -> None:
    race = RaceContext(race_datetime=datetime(2026, 6, 18, 9, 0))
    with pytest.raises(ValidationError):
        race.race_datetime = datetime(2027, 1, 1, 9, 0)
