"""Tests des endpoints /history, /history/{id}, /stats (reader stubé)."""

from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_history_reader
from app.config import get_settings
from app.db.read_models import RunDetail, RunStats, RunSummary
from app.main import app

_TOKEN = "secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _summary(run_id: int) -> RunSummary:
    return RunSummary(
        id=run_id,
        created_at=datetime(2026, 6, 20, 12, 0),
        distance_km=10.0,
        race_datetime=datetime(2026, 9, 1, 9, 0),
        generated_by="llm",
        average_pace_sec_per_km=300.0,
        guardrails_passed=True,
        deviation_vs_baseline_pct=-2.0,
        latency_ms=1500.0,
    )


class _FakeReader:
    async def list_runs(self, *, limit: int, offset: int) -> list[RunSummary]:
        return [_summary(2), _summary(1)][offset : offset + limit]

    async def get_run(self, run_id: int) -> RunDetail | None:
        if run_id != 1:
            return None
        return RunDetail(
            **_summary(1).model_dump(),
            gpx_hash="abc",
            elevation_gain_m=100.0,
            elevation_loss_m=80.0,
            start_lat=43.0,
            start_lon=-1.0,
            athlete={"vo2max": 45},
            weather=None,
            surface=None,
            strategy={"generated_by": "llm", "km_plans": []},
        )

    async def compute_stats(self) -> RunStats:
        return RunStats(
            total_runs=4,
            llm_runs=3,
            baseline_runs=1,
            llm_share_pct=75.0,
            guardrails_passed_pct=75.0,
            calibration_used_pct=50.0,
            avg_deviation_vs_baseline_pct=-1.5,
            avg_latency_ms=1600.0,
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("API_TOKEN", _TOKEN)
    get_settings.cache_clear()
    app.dependency_overrides[get_history_reader] = _FakeReader
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_history_requires_auth(client: TestClient) -> None:
    assert client.get("/history").status_code == 401


def test_history_lists_runs(client: TestClient) -> None:
    response = client.get("/history", headers=_AUTH, params={"limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["generated_by"] == "llm"


def test_history_detail_found(client: TestClient) -> None:
    response = client.get("/history/1", headers=_AUTH)
    assert response.status_code == 200
    assert response.json()["gpx_hash"] == "abc"


def test_history_detail_not_found(client: TestClient) -> None:
    assert client.get("/history/999", headers=_AUTH).status_code == 404


def test_stats_returns_kpis(client: TestClient) -> None:
    response = client.get("/stats", headers=_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["total_runs"] == 4
    assert body["llm_share_pct"] == 75.0
