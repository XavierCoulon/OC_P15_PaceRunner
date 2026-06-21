"""Tests des appels d'aperçu du client front (profil, athlète, météo), respx."""

import httpx
import pytest
import respx

from api_client import BackendError, fetch_athlete, fetch_profile, fetch_weather

_PROFILE = "http://localhost:8000/profile"
_ATHLETE = "http://localhost:8000/athlete"
_WEATHER = "http://localhost:8000/weather"


@respx.mock
def test_fetch_profile_returns_course() -> None:
    respx.post(_PROFILE).mock(
        return_value=httpx.Response(
            200,
            json={
                "distance_km": 5.0,
                "elevation_gain_m": 100.0,
                "elevation_loss_m": 80.0,
                "start_lat": 43.0,
                "start_lon": 6.0,
                "segments": [],
                "route": [{"lat": 43.0, "lon": 6.0}, {"lat": 43.01, "lon": 6.0}],
            },
        )
    )
    course = fetch_profile(gpx_bytes=b"<gpx/>", filename="c.gpx")
    assert course.distance_km == 5.0
    assert len(course.route) == 2


@respx.mock
def test_fetch_profile_invalid_gpx() -> None:
    respx.post(_PROFILE).mock(return_value=httpx.Response(422, json={"detail": "illisible"}))
    with pytest.raises(BackendError, match="GPX"):
        fetch_profile(gpx_bytes=b"x", filename="c.gpx")


@respx.mock
def test_fetch_athlete_returns_profile() -> None:
    respx.get(_ATHLETE).mock(
        return_value=httpx.Response(200, json={"threshold_pace_sec_per_km": 290.0, "vo2max": 45.0})
    )
    athlete = fetch_athlete()
    assert athlete.threshold_pace_sec_per_km == 290.0


@respx.mock
def test_fetch_weather_returns_context() -> None:
    respx.get(_WEATHER).mock(
        return_value=httpx.Response(
            200, json={"source": "forecast", "temperature_c": 18.0, "weather_code": 1}
        )
    )
    weather = fetch_weather(lat=43.0, lon=6.0, race_datetime_iso="2026-09-01T09:00:00")
    assert weather.source == "forecast"
    assert weather.weather_code == 1
