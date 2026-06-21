"""Tests de la préparation des données de visualisation (front/viz.py)."""

from datetime import datetime

from app.db.read_models import RunSummary
from app.domain.models import KmPlan, PaceStrategy
from viz import history_rows, km_table_rows, strategy_rows


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


def test_km_table_rows() -> None:
    rows = km_table_rows(_strategy())
    assert len(rows) == 2
    assert rows[1]["Km"] == 2
    assert rows[1]["Allure"] == "6:00/km"
    assert rows[1]["Effort"] == "hard"
    assert rows[1]["Pente %"] == 6.0


def test_history_rows() -> None:
    run = RunSummary(
        id=7,
        created_at=datetime(2026, 6, 20, 12, 30),
        distance_km=10.17,
        race_datetime=datetime(2026, 9, 1, 9, 0),
        generated_by="baseline",
        average_pace_sec_per_km=318.0,
        guardrails_passed=False,
        deviation_vs_baseline_pct=-11.1,
        latency_ms=1500.0,
    )
    rows = history_rows([run])
    assert rows[0]["Id"] == 7
    assert rows[0]["Origine"] == "Repli"
    assert rows[0]["Allure moy."] == "5:18/km"
    assert rows[0]["Garde-fous"] == "non"
