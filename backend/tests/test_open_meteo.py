"""Tests du WeatherProvider Open-Meteo — tier prévision (≤16 j)."""

from datetime import date, datetime, time, timedelta

import httpx
import respx

from app.adapters.open_meteo import OpenMeteoWeatherProvider

_FORECAST = "https://api.open-meteo.com/v1/forecast"
_AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

_LAT, _LON = 43.47, -1.48


def _when(days_ahead: int, hour: int = 9) -> datetime:
    return datetime.combine(date.today() + timedelta(days=days_ahead), time(hour, 0))


def _archive_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "daily": {
                "temperature_2m_mean": [15.0],
                "temperature_2m_max": [20.0],
                "temperature_2m_min": [10.0],
                "precipitation_sum": [2.0],
                "wind_speed_10m_max": [18.0],
            }
        },
    )


@respx.mock
async def test_forecast_tier_returns_conditions() -> None:
    when = _when(3)
    hour_key = when.strftime("%Y-%m-%dT%H:00")
    day = when.date().isoformat()
    respx.get(url__startswith=_FORECAST).mock(
        return_value=httpx.Response(
            200,
            json={
                "hourly": {
                    "time": [hour_key],
                    "temperature_2m": [18.5],
                    "precipitation": [0.2],
                    "wind_speed_10m": [12.0],
                    "weather_code": [3],
                },
                "daily": {
                    "time": [day],
                    "temperature_2m_max": [24.0],
                    "temperature_2m_min": [14.0],
                },
            },
        )
    )
    respx.get(url__startswith=_AIR).mock(
        return_value=httpx.Response(
            200, json={"hourly": {"time": [hour_key], "european_aqi": [42.0]}}
        )
    )
    respx.get(url__startswith=_ARCHIVE).mock(return_value=_archive_response())

    weather = await OpenMeteoWeatherProvider().get_weather(_LAT, _LON, when)

    assert weather.source == "forecast"
    assert weather.horizon_days == 3
    assert weather.temperature_c == 18.5
    assert weather.precipitation_mm == 0.2
    assert weather.wind_speed_kmh == 12.0
    assert weather.temperature_max_c == 24.0
    assert weather.temperature_min_c == 14.0
    assert weather.air_quality_index == 42.0
    assert weather.weather_code == 3
    assert len(weather.history) == 3  # 3 dernières années


@respx.mock
async def test_degrades_on_forecast_error() -> None:
    respx.get(url__startswith=_ARCHIVE).mock(return_value=_archive_response())
    respx.get(url__startswith=_FORECAST).mock(return_value=httpx.Response(500))
    weather = await OpenMeteoWeatherProvider().get_weather(_LAT, _LON, _when(3))
    assert weather.source is None
    assert weather.temperature_c is None
    assert weather.horizon_days == 3


@respx.mock
async def test_far_date_falls_back_to_last_year_with_history() -> None:
    # Course lointaine (~6 mois) → météo non disponible → relevés de l'an dernier + historique.
    respx.get(url__startswith=_ARCHIVE).mock(return_value=_archive_response())

    weather = await OpenMeteoWeatherProvider().get_weather(_LAT, _LON, _when(200))

    assert weather.source == "last_year"
    assert weather.horizon_days == 200
    assert weather.temperature_c == 15.0  # = relevés de l'an dernier
    assert weather.precipitation_mm == 2.0
    assert weather.wind_speed_kmh == 18.0
    assert len(weather.history) == 3
    assert weather.history[0].temperature_c == 15.0


@respx.mock
async def test_far_date_degrades_when_archive_unavailable() -> None:
    respx.get(url__startswith=_ARCHIVE).mock(return_value=httpx.Response(500))
    weather = await OpenMeteoWeatherProvider().get_weather(_LAT, _LON, _when(200))
    assert weather.source is None
    assert weather.temperature_c is None
    assert weather.horizon_days == 200
