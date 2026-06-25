"""AthleteProvider : forme de l'athlète via COROS.

Agrège trois outils COROS (chacun renvoyant un texte formaté), avec dégradation
gracieuse **par appel** — un outil indisponible n'empêche pas les autres :

- `queryFitnessAssessmentOverview` → allure seuil, VO2max ;
- `queryRecoveryStatus` → % et niveau de récupération (fraîcheur jour J) ;
- `queryUserInfo` → poids (utile au *grade-adjusted pace*).
"""

import re

from app.adapters.coros_client import CorosClient, MCPToolClient
from app.domain.models import AthleteProfile

_FITNESS_TOOL = "queryFitnessAssessmentOverview"
_RECOVERY_TOOL = "queryRecoveryStatus"
_USER_TOOL = "queryUserInfo"


def _parse_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def _parse_pace(text: str) -> float | None:
    """« Threshold Pace: 4:52 /km » → 292.0 (secondes par km)."""
    match = re.search(r"Threshold Pace:\s*(\d+):(\d{2})", text)
    return float(int(match.group(1)) * 60 + int(match.group(2))) if match else None


def _parse_recovery_level(text: str) -> str | None:
    """« Level: Moderate training recommended » → ce libellé."""
    match = re.search(r"Level:\s*(.+)", text)
    return match.group(1).strip() if match else None


class CorosAthleteProvider:
    """Implémente le port `AthleteProvider`."""

    def __init__(self, client: MCPToolClient | None = None) -> None:
        self._client: MCPToolClient = client or CorosClient()

    async def get_athlete_profile(self) -> AthleteProfile:
        fitness = await self._safe_call(_FITNESS_TOOL)
        recovery = await self._safe_call(_RECOVERY_TOOL)
        user = await self._safe_call(_USER_TOOL)
        return AthleteProfile(
            threshold_pace_sec_per_km=_parse_pace(fitness),
            vo2max=_parse_float(r"VO2max:\s*([0-9]+(?:\.[0-9]+)?)", fitness),
            recovery_pct=_parse_float(r"Recovery:\s*([0-9]+(?:\.[0-9]+)?)\s*%", recovery),
            recovery_status=_parse_recovery_level(recovery),
            weight_kg=_parse_float(r"Weight:\s*([0-9]+(?:\.[0-9]+)?)\s*kg", user),
        )

    async def _safe_call(self, tool: str) -> str:
        """Appelle un outil COROS avec **un retry** (COROS flaky : timeouts/sessions en rafale).

        Renvoie une chaîne vide après échec (dégradation gracieuse).
        """
        for _ in range(2):
            try:
                text = await self._client.call_tool(tool, {})
                if text:
                    return text
            except Exception:
                continue
        return ""
