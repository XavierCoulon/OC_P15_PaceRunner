"""Tests de l'adapter LLM OpenAI-compatible (réseau stubé via respx)."""

import json
from datetime import datetime

import httpx
import pytest
import respx

from app.adapters.llm_openai import LLMGenerationError, OpenAICompatibleStrategyGenerator
from app.domain.models import CourseProfile, ElevationSegment, PaceStrategy, RaceContext

_CHAT = "http://localhost:11434/v1/chat/completions"


def _course() -> CourseProfile:
    return CourseProfile(
        distance_km=2.0,
        elevation_gain_m=10.0,
        elevation_loss_m=0.0,
        start_lat=43.0,
        start_lon=-1.0,
        segments=[
            ElevationSegment(
                km_index=1,
                distance_km=1.0,
                elevation_gain_m=0,
                elevation_loss_m=0,
                gradient_pct=0.0,
            ),
            ElevationSegment(
                km_index=2,
                distance_km=1.0,
                elevation_gain_m=10,
                elevation_loss_m=0,
                gradient_pct=1.0,
            ),
        ],
    )


def _race() -> RaceContext:
    return RaceContext(race_datetime=datetime(2026, 9, 1, 9, 0))


def _valid_content() -> str:
    return json.dumps(
        {
            "distance_km": 2.0,
            "estimated_time_sec": 600.0,
            "average_pace_sec_per_km": 300.0,
            "km_plans": [
                {
                    "km_index": 1,
                    "target_pace_sec_per_km": 300,
                    "effort": "steady",
                    "gradient_pct": 0.0,
                },
                {
                    "km_index": 2,
                    "target_pace_sec_per_km": 300,
                    "effort": "hard",
                    "gradient_pct": 1.0,
                },
            ],
            "summary": "Plan régulier.",
            "generated_by": "model",
        }
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def _generate() -> PaceStrategy:
    return await OpenAICompatibleStrategyGenerator().generate(_course(), _race(), None, None, None)


@respx.mock
async def test_generate_returns_validated_strategy() -> None:
    respx.post(_CHAT).mock(return_value=_chat_response(_valid_content()))
    strategy = await _generate()
    assert strategy.generated_by == "llm"  # provenance imposée côté serveur
    assert len(strategy.km_plans) == 2
    assert strategy.km_plans[1].effort == "hard"


@respx.mock
async def test_generate_retries_on_invalid_then_succeeds() -> None:
    respx.post(_CHAT).mock(
        side_effect=[_chat_response("pas du json"), _chat_response(_valid_content())]
    )
    strategy = await _generate()
    assert strategy.generated_by == "llm"
    assert respx.calls.call_count == 2


@respx.mock
async def test_generate_raises_after_two_invalid() -> None:
    respx.post(_CHAT).mock(
        side_effect=[_chat_response("pas du json"), _chat_response("toujours pas")]
    )
    with pytest.raises(LLMGenerationError):
        await _generate()
