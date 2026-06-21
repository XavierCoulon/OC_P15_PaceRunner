"""Tests de la préparation des données de visualisation (front/viz.py)."""

from app.domain.models import KmPlan, PaceStrategy
from viz import strategy_rows


def _strategy() -> PaceStrategy:
    return PaceStrategy(
        distance_km=2.0,
        estimated_time_sec=660.0,
        average_pace_sec_per_km=330.0,
        km_plans=[
            KmPlan(km_index=1, target_pace_sec_per_km=300, effort="steady", gradient_pct=0.0),
            KmPlan(km_index=2, target_pace_sec_per_km=360, effort="hard", gradient_pct=6.0),
        ],
        generated_by="llm",
    )


def test_strategy_rows_builds_profile_and_pace() -> None:
    rows = strategy_rows(_strategy())
    assert len(rows) == 2
    # dénivelé cumulé : km1 (0%) → 0 m, km2 (+6% sur 1 km) → +60 m
    assert rows[0]["elevation_m"] == 0.0
    assert rows[1]["elevation_m"] == 60.0
    # allure formatée
    assert rows[1]["pace_label"] == "6:00"
    assert rows[1]["effort"] == "hard"
    assert rows[1]["gradient_pct"] == 6.0
