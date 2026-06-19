"""Tests des providers COROS (parsing, mapping, dégradation, mock)."""

from typing import Any

from app.adapters.coros_athlete import CorosAthleteProvider, parse_fitness_overview
from app.adapters.coros_mock import CorosMockAthleteProvider

_SAMPLE = (
    "Fitness Assessment Overview\n========================\n\n"
    "VO2max: 45\nRunning Level: 77\nThreshold Pace: 4:52 /km\n"
    "5 km Prediction: 23:25\nMarathon Prediction: 3:52:51"
)


class _FakeClient:
    def __init__(self, text: str | None = None, exc: Exception | None = None) -> None:
        self._text = text
        self._exc = exc

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if self._exc is not None:
            raise self._exc
        assert self._text is not None
        return self._text


def test_parse_fitness_overview() -> None:
    profile = parse_fitness_overview(_SAMPLE)
    assert profile.threshold_pace_sec_per_km == 292.0  # 4:52
    assert profile.vo2max == 45.0


def test_parse_missing_fields_returns_none() -> None:
    profile = parse_fitness_overview("aucune donnée exploitable")
    assert profile.threshold_pace_sec_per_km is None
    assert profile.vo2max is None


async def test_provider_maps_tool_text() -> None:
    provider = CorosAthleteProvider(client=_FakeClient(text=_SAMPLE))
    profile = await provider.get_athlete_profile()
    assert profile.threshold_pace_sec_per_km == 292.0
    assert profile.vo2max == 45.0


async def test_provider_returns_empty_profile_on_error() -> None:
    provider = CorosAthleteProvider(client=_FakeClient(exc=RuntimeError("COROS KO")))
    profile = await provider.get_athlete_profile()
    assert profile.threshold_pace_sec_per_km is None
    assert profile.vo2max is None


async def test_mock_provider_returns_seeded_profile() -> None:
    profile = await CorosMockAthleteProvider().get_athlete_profile()
    assert profile.threshold_pace_sec_per_km == 292.0
    assert profile.vo2max == 45.0
