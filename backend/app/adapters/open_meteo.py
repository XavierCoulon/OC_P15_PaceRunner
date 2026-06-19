"""WeatherProvider : conditions au point de départ via Open-Meteo (REST, sans clé).

Route selon l'horizon de la course (cf. docs/02-audit-data.md) :
- ≤ 16 j → **prévision** (Forecast API) + qualité de l'air (≤ ~5 j) ;
- 16 j–7 mois → tendance saisonnière (à venir) ;
- au-delà → climatologie ERA5 (à venir).

Dégradation gracieuse : toute panne renvoie un `WeatherContext` partiel (au pire vide).
"""

from datetime import date, datetime
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.domain.models import WeatherContext

_FORECAST_HORIZON_DAYS = 16
_AIR_QUALITY_HORIZON_DAYS = 5


class OpenMeteoWeatherProvider:
    """Implémente le port `WeatherProvider`."""

    def __init__(self, settings: Settings | None = None) -> None:
        config = settings or get_settings()
        self._forecast_url = config.open_meteo_forecast_url
        self._air_quality_url = config.open_meteo_air_quality_url
        self._timeout = config.http_timeout_seconds

    async def get_weather(self, lat: float, lon: float, when: datetime) -> WeatherContext:
        horizon = (when.date() - date.today()).days
        try:
            if 0 <= horizon <= _FORECAST_HORIZON_DAYS:
                return await self._forecast(lat, lon, when, horizon)
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            pass
        # Tiers saisonnier / climatologie : incréments suivants.
        return WeatherContext(horizon_days=horizon)

    async def _forecast(
        self, lat: float, lon: float, when: datetime, horizon: int
    ) -> WeatherContext:
        day = when.date().isoformat()
        hour_key = when.strftime("%Y-%m-%dT%H:00")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            weather = await self._fetch_forecast(client, lat, lon, day, hour_key)
            aqi = None
            if horizon <= _AIR_QUALITY_HORIZON_DAYS:
                aqi = await self._fetch_air_quality(client, lat, lon, day, hour_key)
        return WeatherContext(
            source="forecast", horizon_days=horizon, air_quality_index=aqi, **weather
        )

    async def _fetch_forecast(
        self, client: httpx.AsyncClient, lat: float, lon: float, day: str, hour_key: str
    ) -> dict[str, float | None]:
        params: dict[str, float | str] = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,precipitation,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min",
            "start_date": day,
            "end_date": day,
            "timezone": "auto",
        }
        response = await client.get(self._forecast_url, params=params)
        response.raise_for_status()
        data = response.json()
        hourly = data.get("hourly", {})
        index = _hour_index(hourly.get("time", []), hour_key)
        daily = data.get("daily", {})
        return {
            "temperature_c": _at(hourly.get("temperature_2m"), index),
            "precipitation_mm": _at(hourly.get("precipitation"), index),
            "wind_speed_kmh": _at(hourly.get("wind_speed_10m"), index),
            "temperature_max_c": _at(daily.get("temperature_2m_max"), 0),
            "temperature_min_c": _at(daily.get("temperature_2m_min"), 0),
        }

    async def _fetch_air_quality(
        self, client: httpx.AsyncClient, lat: float, lon: float, day: str, hour_key: str
    ) -> float | None:
        params: dict[str, float | str] = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "european_aqi",
            "start_date": day,
            "end_date": day,
            "timezone": "auto",
        }
        response = await client.get(self._air_quality_url, params=params)
        response.raise_for_status()
        hourly = response.json().get("hourly", {})
        return _at(hourly.get("european_aqi"), _hour_index(hourly.get("time", []), hour_key))


def _hour_index(times: list[str], hour_key: str) -> int | None:
    return times.index(hour_key) if hour_key in times else None


def _at(values: list[Any] | None, index: int | None) -> float | None:
    if values is None or index is None or index >= len(values):
        return None
    value = values[index]
    return float(value) if value is not None else None
