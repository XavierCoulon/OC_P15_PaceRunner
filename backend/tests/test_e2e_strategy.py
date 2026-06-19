"""Test d'intégration E2E du pipeline (H2).

Exécute `build_strategy` avec les **vrais adapters** ; seules les API externes sont
simulées via respx (Open Topo Data, Open-Meteo, LLM). COROS se dégrade gracieusement
(pas d'identifiants en test) → AthleteProfile vide, le pipeline continue.
"""

import json
from datetime import date, datetime, time, timedelta

import httpx
import respx

from app.adapters.coros_athlete import CorosAthleteProvider
from app.adapters.llm_openai import OpenAICompatibleStrategyGenerator
from app.adapters.open_meteo import OpenMeteoWeatherProvider
from app.adapters.open_topo_data import OpenTopoDataProvider
from app.domain.models import PaceStrategy, RaceContext
from app.services.strategy_service import build_strategy

_OTD = "https://api.opentopodata.org/v1"
_FORECAST = "https://api.open-meteo.com/v1/forecast"
_AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
_CHAT = "http://localhost:11434/v1/chat/completions"

_POINTS = 20


def _gpx() -> str:
    # Profil en « tente » : monte puis descend → segments montants et descendants.
    rows = []
    for i in range(_POINTS):
        ele = 10 + min(i, _POINTS - 1 - i) * 8
        rows.append(f'<trkpt lat="{43.0 + i * 0.001}" lon="6.0"><ele>{ele}</ele></trkpt>')
    pts = "".join(rows)
    return (
        '<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{pts}</trkseg></trk></gpx>"
    )


def _when() -> datetime:
    return datetime.combine(date.today() + timedelta(days=3), time(9, 0))


def _otd_handler(request: httpx.Request) -> httpx.Response:
    locations = request.url.params.get("locations", "")
    count = len(locations.split("|")) if locations else 0
    results = [{"elevation": 10.0 + min(i, count - 1 - i) * 8} for i in range(count)]
    return httpx.Response(200, json={"status": "OK", "results": results})


def _forecast_response() -> httpx.Response:
    hour_key = _when().strftime("%Y-%m-%dT%H:00")
    return httpx.Response(
        200,
        json={
            "hourly": {
                "time": [hour_key],
                "temperature_2m": [18.0],
                "precipitation": [0.0],
                "wind_speed_10m": [10.0],
            },
            "daily": {"temperature_2m_max": [24.0], "temperature_2m_min": [12.0]},
        },
    )


def _air_response() -> httpx.Response:
    hour_key = _when().strftime("%Y-%m-%dT%H:00")
    return httpx.Response(200, json={"hourly": {"time": [hour_key], "european_aqi": [40.0]}})


def _llm_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    user = next(m["content"] for m in reversed(body["messages"]) if '"course"' in m["content"])
    payload = json.loads(user)
    segments = payload["course"]["segments"]
    km_plans = [
        {
            "km_index": s["km_index"],
            "target_pace_sec_per_km": 300 + s["gradient_pct"] * 4,  # montée plus lente
            "effort": "steady",
            "gradient_pct": s["gradient_pct"],
        }
        for s in segments
    ]
    strategy = {
        "distance_km": payload["course"]["distance_km"],
        "estimated_time_sec": 1.0,
        "average_pace_sec_per_km": 1.0,
        "km_plans": km_plans,
        "summary": "Plan d'intégration.",
        "generated_by": "model",
    }
    content = json.dumps(strategy)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def _run() -> PaceStrategy:
    return await build_strategy(
        _gpx(),
        RaceContext(race_datetime=_when(), goal="finir"),
        elevation=OpenTopoDataProvider(),
        athlete_provider=CorosAthleteProvider(),
        weather=OpenMeteoWeatherProvider(),
        generator=OpenAICompatibleStrategyGenerator(),
    )


@respx.mock
async def test_pipeline_end_to_end_with_real_adapters() -> None:
    respx.get(url__startswith=_OTD).mock(side_effect=_otd_handler)
    respx.get(url__startswith=_FORECAST).mock(return_value=_forecast_response())
    respx.get(url__startswith=_AIR).mock(return_value=_air_response())
    respx.post(_CHAT).mock(side_effect=_llm_handler)

    strategy = await _run()

    assert strategy.generated_by == "llm"
    assert strategy.distance_km > 0
    assert len(strategy.km_plans) >= 1
    assert strategy.average_pace_sec_per_km > 0


@respx.mock
async def test_pipeline_falls_back_to_baseline_when_llm_fails() -> None:
    respx.get(url__startswith=_OTD).mock(side_effect=_otd_handler)
    respx.get(url__startswith=_FORECAST).mock(return_value=_forecast_response())
    respx.get(url__startswith=_AIR).mock(return_value=_air_response())
    respx.post(_CHAT).mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "pas du json"}}]}
        )
    )

    strategy = await _run()

    assert strategy.generated_by == "baseline"
    assert len(strategy.km_plans) >= 1
