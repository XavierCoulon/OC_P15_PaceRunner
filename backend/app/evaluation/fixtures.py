"""Cas d'évaluation : parcours types (plat, vallonné, long, pentes extrêmes)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import AthleteProfile, CourseProfile, ElevationSegment, RaceContext

_ATHLETE = AthleteProfile(threshold_pace_sec_per_km=292.0, recovery_pct=90.0, weight_kg=71.0)
_RACE = RaceContext(race_datetime=datetime(2026, 9, 1, 9, 0))


@dataclass(frozen=True)
class EvalCase:
    name: str
    course: CourseProfile
    athlete: AthleteProfile
    race: RaceContext


def _course(gradients: Sequence[float]) -> CourseProfile:
    segments = [
        ElevationSegment(
            km_index=i + 1,
            distance_km=1.0,
            elevation_gain_m=max(g, 0.0) * 10,
            elevation_loss_m=max(-g, 0.0) * 10,
            gradient_pct=g,
        )
        for i, g in enumerate(gradients)
    ]
    return CourseProfile(
        distance_km=float(len(gradients)),
        elevation_gain_m=sum(max(g, 0.0) * 10 for g in gradients),
        elevation_loss_m=sum(max(-g, 0.0) * 10 for g in gradients),
        start_lat=43.0,
        start_lon=-1.0,
        segments=segments,
    )


def eval_cases() -> list[EvalCase]:
    return [
        EvalCase("plat_5km", _course([0.0] * 5), _ATHLETE, _RACE),
        EvalCase("vallonné_10km", _course([0, 3, 5, 2, -4, -2, 4, 6, -5, 0]), _ATHLETE, _RACE),
        EvalCase("long_21km", _course([0, 1, 2, 1, 0, -1, 0, 1, 2, 0] * 2 + [0]), _ATHLETE, _RACE),
        EvalCase("pentes_extrêmes_6km", _course([18, 19, -18, 20, -20, -17]), _ATHLETE, _RACE),
    ]
