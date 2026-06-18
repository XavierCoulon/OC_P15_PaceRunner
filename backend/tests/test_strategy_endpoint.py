"""Tests de l'endpoint POST /strategy (1re tranche verticale GPX → profil)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

_TOKEN = "secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _gpx() -> str:
    points = "".join(
        f'<trkpt lat="{45.0 + i * 0.001}" lon="6.0"><ele>{1000.0 + i * 5}</ele></trkpt>'
        for i in range(20)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{points}</trkseg></trk></gpx>"
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("API_TOKEN", _TOKEN)
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def test_strategy_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/strategy",
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 401


def test_strategy_returns_profile(client: TestClient) -> None:
    response = client.post(
        "/strategy",
        headers=_AUTH,
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00", "goal": "finir"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["distance_km"] > 0
    assert body["elevation_gain_m"] > 0
    assert body["start_lat"] == pytest.approx(45.0)
    assert len(body["segments"]) >= 1


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
