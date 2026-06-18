"""Tests de l'authentification par token Bearer (require_api_token)."""

from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.security import require_api_token
from app.config import get_settings


def _build_client() -> TestClient:
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_api_token)])
    def protected() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


@pytest.fixture
def client_with_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("API_TOKEN", "secret-token")
    get_settings.cache_clear()
    yield _build_client()
    get_settings.cache_clear()


def test_missing_token_returns_401(client_with_token: TestClient) -> None:
    assert client_with_token.get("/protected").status_code == 401


def test_invalid_token_returns_401(client_with_token: TestClient) -> None:
    response = client_with_token.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_valid_token_returns_200(client_with_token: TestClient) -> None:
    response = client_with_token.get("/protected", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_unconfigured_token_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        response = _build_client().get("/protected", headers={"Authorization": "Bearer anything"})
        assert response.status_code == 503
    finally:
        get_settings.cache_clear()
