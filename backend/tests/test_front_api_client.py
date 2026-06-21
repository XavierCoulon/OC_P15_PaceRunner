"""Tests du client API du front (front/api_client.py), réseau stubé via respx."""

import json

import httpx
import pytest
import respx

from api_client import BackendError, generate_strategy
from app.domain.models import StrategyResponse

_URL = "http://localhost:8000/strategy"


def _valid_response_json() -> dict[str, object]:
    return {
        "strategy": {
            "distance_km": 5.0,
            "estimated_time_sec": 1500.0,
            "average_pace_sec_per_km": 300.0,
            "km_plans": [
                {
                    "km_index": 1,
                    "target_pace_sec_per_km": 300,
                    "effort": "steady",
                    "gradient_pct": 0.0,
                }
            ],
            "summary": "ok",
            "generated_by": "llm",
        },
        "course": {
            "distance_km": 5.0,
            "elevation_gain_m": 120.0,
            "elevation_loss_m": 120.0,
            "start_lat": 43.0,
            "start_lon": -1.0,
            "segments": [],
        },
        "athlete": {"threshold_pace_sec_per_km": 290.0},
        "weather": {"source": "forecast", "temperature_c": 18.0},
    }


def _call() -> StrategyResponse:
    return generate_strategy(
        gpx_bytes=b"<gpx/>",
        filename="course.gpx",
        race_datetime_iso="2026-09-01T09:00:00",
        goal="x",
    )


@respx.mock
def test_returns_validated_strategy() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, json=_valid_response_json()))
    response = _call()
    assert response.strategy.generated_by == "llm"
    assert len(response.strategy.km_plans) == 1
    assert response.course.elevation_gain_m == 120.0
    assert response.weather is not None and response.weather.source == "forecast"


@respx.mock
def test_unauthorized_raises_backend_error() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(401, json={"detail": "Token invalide"}))
    with pytest.raises(BackendError, match="Authentification"):
        _call()


@respx.mock
def test_invalid_gpx_raises_backend_error() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(422, json={"detail": "GPX illisible"}))
    with pytest.raises(BackendError, match="GPX"):
        _call()


@respx.mock
def test_unreachable_backend_raises_backend_error() -> None:
    respx.post(_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(BackendError, match="injoignable"):
        _call()


@respx.mock
def test_invalid_payload_raises_backend_error() -> None:
    respx.post(_URL).mock(return_value=httpx.Response(200, content=json.dumps({"bad": 1})))
    with pytest.raises(BackendError, match="invalide"):
        _call()
