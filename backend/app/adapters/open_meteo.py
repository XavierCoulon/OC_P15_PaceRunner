"""WeatherProvider : conditions au point de départ via Open-Meteo (REST, sans clé).

Route selon l'horizon de la course (cf. docs/02-audit-data.md) :
- ≤ 16 j → **prévision** (Forecast API) + qualité de l'air (≤ ~5 j) ;
- au-delà → **relevés de l'an dernier** (ERA5) : la météo réelle n'est pas encore disponible.

Dans les deux cas, on joint l'**historique des 3 dernières années** à la même date (ERA5).
Dégradation gracieuse : toute panne renvoie un `WeatherContext` partiel (au pire vide).
"""

from datetime import date, datetime
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.domain.models import WeatherContext, YearlyWeather

_FORECAST_HORIZON_DAYS = 16
_AIR_QUALITY_HORIZON_DAYS = 5
_HISTORY_YEARS = 3


class OpenMeteoWeatherProvider:
    """Implémente le port `WeatherProvider`."""

    def __init__(self, settings: Settings | None = None) -> None:
        config = settings or get_settings()
        self._forecast_url = config.open_meteo_forecast_url
        self._air_quality_url = config.open_meteo_air_quality_url
        self._archive_url = config.open_meteo_archive_url
        self._timeout = config.http_timeout_seconds

    async def get_weather(self, lat: float, lon: float, when: datetime) -> WeatherContext:
        horizon = (when.date() - date.today()).days
        try:
            history = await self._fetch_history(lat, lon, when)
            if 0 <= horizon <= _FORECAST_HORIZON_DAYS:
                return await self._forecast(lat, lon, when, horizon, history)
            # Course trop lointaine : la prévision n'existe pas encore → on montre l'an dernier.
            return _from_last_year(horizon, history)
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return WeatherContext(horizon_days=horizon)

    async def _forecast(
        self, lat: float, lon: float, when: datetime, horizon: int, history: list[YearlyWeather]
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
            history=history,
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

    async def historical_daily_temps(
        self, lat: float, lon: float, start: date, end: date
    ) -> dict[date, float]:
        """Température moyenne quotidienne (ERA5) sur une plage, en **un seul appel** (axe B).

        Utilisé pour joindre la météo à l'historique de courses (groupées par lieu). Dégradation
        gracieuse : toute panne renvoie un dictionnaire partiel (au pire vide).
        """
        params: dict[str, float | str] = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_mean",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(self._archive_url, params=params)
                response.raise_for_status()
                daily = response.json().get("daily", {})
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return {}
        times = daily.get("time", []) or []
        temps = daily.get("temperature_2m_mean", []) or []
        result: dict[date, float] = {}
        for day_str, temp in zip(times, temps, strict=False):
            if temp is not None:
                result[date.fromisoformat(day_str)] = float(temp)
        return result

    async def _fetch_history(self, lat: float, lon: float, when: datetime) -> list[YearlyWeather]:
        """Relevés des 3 dernières années à la même date calendaire (ERA5), an dernier en tête."""
        years: list[YearlyWeather] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for offset in range(1, _HISTORY_YEARS + 1):
                try:
                    day = date(when.year - offset, when.month, when.day)
                except ValueError:
                    continue  # 29 février d'une année non bissextile
                daily = await self._fetch_archive_day(client, lat, lon, day.isoformat())
                if daily is None:
                    continue
                years.append(
                    YearlyWeather(
                        year=day.year,
                        temperature_c=daily["mean"],
                        precipitation_mm=daily["precip"],
                        wind_speed_kmh=daily["wind"],
                    )
                )
        return years

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


def _from_last_year(horizon: int, history: list[YearlyWeather]) -> WeatherContext:
    """Météo de repli quand la prévision n'existe pas encore : relevés de l'an dernier."""
    if not history:
        return WeatherContext(horizon_days=horizon, history=history)
    last = history[0]  # année la plus récente (offset 1)
    return WeatherContext(
        source="last_year",
        horizon_days=horizon,
        temperature_c=last.temperature_c,
        precipitation_mm=last.precipitation_mm,
        wind_speed_kmh=last.wind_speed_kmh,
        history=history,
    )


def _hour_index(times: list[str], hour_key: str) -> int | None:
    return times.index(hour_key) if hour_key in times else None


def _at(values: list[Any] | None, index: int | None) -> float | None:
    if values is None or index is None or index >= len(values):
        return None
    value = values[index]
    return float(value) if value is not None else None
