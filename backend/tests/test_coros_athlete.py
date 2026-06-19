"""Tests des providers COROS (mapping multi-outils, dégradation, mock)."""

from typing import Any

from app.adapters.coros_athlete import CorosAthleteProvider
from app.adapters.coros_mock import CorosMockAthleteProvider

_FITNESS = "VO2max: 45\nRunning Level: 77\nThreshold Pace: 4:52 /km"
_RECOVERY = (
    "Recovery Status\nRecovery: 87%\nLevel: Moderate training recommended\nFull Recovery: 14h"
)
_USER = "Height: 179.0 cm\nWeight: 71.2 kg\nBirthday: 1977-05-13 (Age: 49)\nGender: Male"

_RESPONSES = {
    "queryFitnessAssessmentOverview": _FITNESS,
    "queryRecoveryStatus": _RECOVERY,
    "queryUserInfo": _USER,
}


class _FakeClient:
    """Renvoie un texte par outil ; lève une erreur pour les outils absents de `responses`."""

    def __init__(self, responses: dict[str, str] | None = None, fail_all: bool = False) -> None:
        self._responses = responses or {}
        self._fail_all = fail_all

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if self._fail_all or name not in self._responses:
            raise RuntimeError(f"COROS KO: {name}")
        return self._responses[name]


async def test_provider_maps_all_tools() -> None:
    provider = CorosAthleteProvider(client=_FakeClient(_RESPONSES))
    profile = await provider.get_athlete_profile()
    assert profile.threshold_pace_sec_per_km == 292.0
    assert profile.vo2max == 45.0
    assert profile.recovery_pct == 87.0
    assert profile.recovery_status == "Moderate training recommended"
    assert profile.weight_kg == 71.2


async def test_provider_partial_degradation() -> None:
    # Seul l'outil fitness répond ; recovery et userInfo échouent.
    provider = CorosAthleteProvider(
        client=_FakeClient({"queryFitnessAssessmentOverview": _FITNESS})
    )
    profile = await provider.get_athlete_profile()
    assert profile.threshold_pace_sec_per_km == 292.0
    assert profile.recovery_pct is None
    assert profile.weight_kg is None


async def test_provider_full_degradation() -> None:
    provider = CorosAthleteProvider(client=_FakeClient(fail_all=True))
    profile = await provider.get_athlete_profile()
    assert profile.threshold_pace_sec_per_km is None
    assert profile.vo2max is None
    assert profile.recovery_pct is None
    assert profile.weight_kg is None


async def test_mock_provider_returns_seeded_profile() -> None:
    profile = await CorosMockAthleteProvider().get_athlete_profile()
    assert profile.threshold_pace_sec_per_km == 292.0
    assert profile.recovery_pct == 87.0
    assert profile.weight_kg == 71.2
