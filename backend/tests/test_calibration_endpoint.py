"""Tests des endpoints /calibration (statut + refresh), providers stubés."""

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.routes import (
    get_activity_history_provider,
    get_activity_repository,
    get_athlete_provider,
    get_calibration_store,
    get_historical_weather_provider,
)
from app.config import get_settings
from app.db.calibration import NullCalibrationStore
from app.db.read_models import CalibrationStatus
from app.domain.models import ActivitySummary, AthleteProfile
from app.main import app

_TOKEN = "secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _activity(label: str, ts: int) -> ActivitySummary:
    return ActivitySummary(
        label_id=label,
        sport_type=100,
        start_timestamp=ts,
        activity_date=date(2026, 6, 1),
        distance_km=10.0,
        duration_s=3600,
    )


class _FakeProvider:
    async def list_activities(
        self, *, since: int | None = None, sport_codes: list[int] | None = None
    ) -> list[ActivitySummary]:
        activities = [_activity("a", 100), _activity("b", 200)]
        return [a for a in activities if since is None or a.start_timestamp > since]


class _FakeRepo:
    def __init__(self) -> None:
        self.store: dict[str, ActivitySummary] = {}

    async def upsert(self, activities: list[ActivitySummary]) -> int:
        new = [a for a in activities if a.label_id not in self.store]
        for a in new:
            self.store[a.label_id] = a
        return len(new)

    async def last_synced_timestamp(self) -> int | None:
        return max((a.start_timestamp for a in self.store.values()), default=None)

    async def all_activities(self) -> list[ActivitySummary]:
        return list(self.store.values())

    async def set_weather(self, temps: dict[str, float]) -> int:
        return len(temps)

    async def status(self) -> CalibrationStatus:
        return CalibrationStatus(
            activity_count=len(self.store),
            first_activity_date=None,
            last_activity_date=None,
            last_synced_at=None,
            trail_sample_count=0,
            calibration_computed_at=None,
        )


class _FakeAthlete:
    async def get_athlete_profile(self) -> AthleteProfile:
        return AthleteProfile(threshold_pace_sec_per_km=300.0)


class _FakeWeather:
    async def historical_daily_temps(
        self, lat: float, lon: float, start: date, end: date
    ) -> dict[date, float]:
        return {}


@pytest.fixture
def repo() -> _FakeRepo:
    return _FakeRepo()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, repo: _FakeRepo) -> Iterator[TestClient]:
    monkeypatch.setenv("API_TOKEN", _TOKEN)
    get_settings.cache_clear()
    app.dependency_overrides[get_activity_history_provider] = _FakeProvider
    app.dependency_overrides[get_activity_repository] = lambda: repo
    app.dependency_overrides[get_athlete_provider] = _FakeAthlete
    app.dependency_overrides[get_calibration_store] = NullCalibrationStore
    app.dependency_overrides[get_historical_weather_provider] = _FakeWeather
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_calibration_requires_auth(client: TestClient) -> None:
    assert client.get("/calibration").status_code == 401


def test_calibration_status_starts_empty(client: TestClient) -> None:
    response = client.get("/calibration", headers=_AUTH)
    assert response.status_code == 200
    assert response.json()["activity_count"] == 0


def test_refresh_then_status_reflects_ingestion(client: TestClient) -> None:
    refresh = client.post("/calibration/refresh", headers=_AUTH)
    assert refresh.status_code == 200
    body = refresh.json()
    assert body["fetched"] == 2
    assert body["inserted"] == 2
    assert body["status"]["activity_count"] == 2

    # Idempotence : un second refresh n'insère rien.
    again = client.post("/calibration/refresh", headers=_AUTH)
    assert again.json()["inserted"] == 0
