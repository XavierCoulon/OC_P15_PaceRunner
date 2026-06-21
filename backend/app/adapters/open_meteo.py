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
        self._archive_url = config.open_meteo_archive_url
        self._climatology_years = config.climatology_years
        self._timeout = config.http_timeout_seconds

    async def get_weather(self, lat: float, lon: float, when: datetime) -> WeatherContext:
        horizon = (when.date() - date.today()).days
        try:
            if 0 <= horizon <= _FORECAST_HORIZON_DAYS:
                return await self._forecast(lat, lon, when, horizon)
            # Tendance saisonnière (16 j–7 mois) : tier à venir. Au-delà : climatologie.
            return await self._climatology(lat, lon, when, horizon)
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
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
        code = weather.pop("weather_code", None)
        return WeatherContext(
            source="forecast",
            horizon_days=horizon,
            air_quality_index=aqi,
            weather_code=int(code) if code is not None else None,
            **weather,
        )

    async def _fetch_forecast(
        self, client: httpx.AsyncClient, lat: float, lon: float, day: str, hour_key: str
    ) -> dict[str, float | None]:
        params: dict[str, float | str] = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,precipitation,wind_speed_10m,weather_code",
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
            "weather_code": _at(hourly.get("weather_code"), index),
            "temperature_max_c": _at(daily.get("temperature_2m_max"), 0),
            "temperature_min_c": _at(daily.get("temperature_2m_min"), 0),
        }

    async def _climatology(
        self, lat: float, lon: float, when: datetime, horizon: int
    ) -> WeatherContext:
        """Moyenne la même date calendaire sur les N dernières années (ERA5)."""
        means: list[float] = []
        mins: list[float] = []
        maxs: list[float] = []
        precs: list[float] = []
        winds: list[float] = []
        last_year_temp: float | None = None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for offset in range(1, self._climatology_years + 1):
                try:
                    day = date(when.year - offset, when.month, when.day)
                except ValueError:
                    continue  # 29 février d'une année non bissextile
                daily = await self._fetch_archive_day(client, lat, lon, day.isoformat())
                if daily is None:
                    continue
                _append(means, daily["mean"])
                _append(mins, daily["min"])
                _append(maxs, daily["max"])
                _append(precs, daily["precip"])
                _append(winds, daily["wind"])
                if offset == 1:
                    last_year_temp = daily["mean"]
        if not means:
            return WeatherContext(horizon_days=horizon)
        return WeatherContext(
            source="climatology",
            horizon_days=horizon,
            temperature_c=_avg(means),
            temperature_min_c=_avg(mins),
            temperature_max_c=_avg(maxs),
            precipitation_mm=_avg(precs),
            wind_speed_kmh=_avg(winds),
            last_year_temperature_c=last_year_temp,
        )

    async def _fetch_archive_day(
        self, client: httpx.AsyncClient, lat: float, lon: float, day: str
    ) -> dict[str, float | None] | None:
        params: dict[str, float | str] = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_mean,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,wind_speed_10m_max",
            "start_date": day,
            "end_date": day,
            "timezone": "auto",
        }
        try:
            response = await client.get(self._archive_url, params=params)
            response.raise_for_status()
            daily = response.json().get("daily", {})
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return None
        return {
            "mean": _at(daily.get("temperature_2m_mean"), 0),
            "max": _at(daily.get("temperature_2m_max"), 0),
            "min": _at(daily.get("temperature_2m_min"), 0),
            "precip": _at(daily.get("precipitation_sum"), 0),
            "wind": _at(daily.get("wind_speed_10m_max"), 0),
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


def _append(values: list[float], value: float | None) -> None:
    if value is not None:
        values.append(value)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _hour_index(times: list[str], hour_key: str) -> int | None:
    return times.index(hour_key) if hour_key in times else None


def _at(values: list[Any] | None, index: int | None) -> float | None:
    if values is None or index is None or index >= len(values):
        return None
    value = values[index]
    return float(value) if value is not None else None
