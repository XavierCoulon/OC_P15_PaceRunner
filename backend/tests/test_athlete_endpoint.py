"""Tests de l'endpoint GET /athlete (vérification connexion COROS)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.adapters.coros_mock import CorosMockAthleteProvider
from app.api.routes import get_athlete_provider
from app.config import get_settings
from app.main import app

_TOKEN = "secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("API_TOKEN", _TOKEN)
    get_settings.cache_clear()
    app.dependency_overrides[get_athlete_provider] = CorosMockAthleteProvider
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_athlete_requires_auth(client: TestClient) -> None:
    assert client.get("/athlete").status_code == 401


def test_athlete_returns_profile(client: TestClient) -> None:
    response = client.get("/athlete", headers=_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["threshold_pace_sec_per_km"] == 292.0
    assert body["vo2max"] == 45.0
    assert body["recovery_pct"] == 87.0
    assert body["weight_kg"] == 71.2
