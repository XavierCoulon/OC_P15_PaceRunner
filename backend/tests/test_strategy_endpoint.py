"""Tests de l'endpoint POST /strategy (pipeline complet, providers stubés)."""

from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.adapters.coros_mock import CorosMockAthleteProvider
from app.api.routes import (
    get_athlete_provider,
    get_elevation_provider,
    get_strategy_generator,
    get_weather_provider,
)
from app.config import get_settings
from app.domain.models import CourseProfile, PaceStrategy, RaceContext, WeatherContext
from app.main import app

_TOKEN = "secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _gpx() -> str:
    points = "".join(
        f'<trkpt lat="{43.0 + i * 0.001}" lon="6.0"><ele>{1000.0 + i * 5}</ele></trkpt>'
        for i in range(20)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{points}</trkseg></trk></gpx>"
    )


class _FakeElevation:
    async def clean_elevations(self, profile: CourseProfile) -> CourseProfile:
        return profile


class _FakeWeather:
    async def get_weather(self, lat: float, lon: float, when: datetime) -> WeatherContext:
        return WeatherContext()


class _FailingGenerator:
    async def generate(self, *args: object, **kwargs: object) -> PaceStrategy:
        raise RuntimeError("LLM indisponible")  # force le fallback baseline


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("API_TOKEN", _TOKEN)
    get_settings.cache_clear()
    app.dependency_overrides[get_elevation_provider] = _FakeElevation
    app.dependency_overrides[get_athlete_provider] = CorosMockAthleteProvider
    app.dependency_overrides[get_weather_provider] = _FakeWeather
    app.dependency_overrides[get_strategy_generator] = _FailingGenerator
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_strategy_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/strategy",
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 401


def test_strategy_returns_pace_strategy(client: TestClient) -> None:
    response = client.post(
        "/strategy",
        headers=_AUTH,
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00", "goal": "finir"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["distance_km"] > 0
    assert len(body["km_plans"]) >= 1
    # LLM stubé en échec → fallback baseline déterministe.
    assert body["generated_by"] == "baseline"
    assert body["average_pace_sec_per_km"] > 0


def test_strategy_rejects_invalid_gpx(client: TestClient) -> None:
    response = client.post(
        "/strategy",
        headers=_AUTH,
        files={"gpx": ("bad.gpx", "pas du gpx", "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 422


def test_health_remains_public(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_race_context_accepts_goal() -> None:
    assert RaceContext(race_datetime=datetime(2026, 9, 1, 9, 0), goal="finir").goal == "finir"
