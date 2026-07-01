"""Tests des appels lecture du client front (fetch_history / fetch_stats), respx."""

import httpx
import pytest
import respx

from api_client import BackendError, fetch_history, fetch_stats

_HISTORY = "http://localhost:8000/history"
_STATS = "http://localhost:8000/stats"


def _run(run_id: int) -> dict[str, object]:
    return {
        "id": run_id,
        "created_at": "2026-06-20T12:00:00",
        "distance_km": 10.0,
        "race_datetime": "2026-09-01T09:00:00",
        "generated_by": "llm",
        "average_pace_sec_per_km": 300.0,
        "guardrails_passed": True,
        "deviation_vs_baseline_pct": -2.0,
        "latency_ms": 1500.0,
    }


@respx.mock
def test_fetch_history_returns_runs() -> None:
    respx.get(url__startswith=_HISTORY).mock(
        return_value=httpx.Response(200, json=[_run(2), _run(1)])
    )
    runs = fetch_history(limit=10)
    assert [r.id for r in runs] == [2, 1]


@respx.mock
def test_fetch_history_auth_error() -> None:
    respx.get(url__startswith=_HISTORY).mock(return_value=httpx.Response(401))
    with pytest.raises(BackendError, match="Authentification"):
        fetch_history()


@respx.mock
def test_fetch_stats_returns_kpis() -> None:
    respx.get(url__startswith=_STATS).mock(
        return_value=httpx.Response(
            200,
            json={
                "total_runs": 4,
                "llm_runs": 3,
                "baseline_runs": 1,
                "llm_share_pct": 75.0,
                "guardrails_passed_pct": 75.0,
                "calibration_used_pct": 50.0,
                "avg_deviation_vs_baseline_pct": -1.5,
                "avg_latency_ms": 1600.0,
            },
        )
    )
    stats = fetch_stats()
    assert stats.total_runs == 4
    assert stats.llm_share_pct == 75.0
