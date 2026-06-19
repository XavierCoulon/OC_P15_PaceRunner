"""AthleteProvider : forme de l'athlète via COROS.

Appelle l'outil `queryFitnessAssessmentOverview` (qui renvoie un texte formaté) et en
extrait l'allure seuil et le VO2max. En cas d'erreur (identifiants absents, API KO),
renvoie un `AthleteProfile` vide → dégradation gracieuse du pipeline.
"""

import re

from app.adapters.coros_client import CorosClient, MCPToolClient
from app.domain.models import AthleteProfile

_FITNESS_TOOL = "queryFitnessAssessmentOverview"


def parse_fitness_overview(text: str) -> AthleteProfile:
    """Extrait les indicateurs utiles du texte renvoyé par COROS."""
    return AthleteProfile(
        threshold_pace_sec_per_km=_parse_pace(text),
        vo2max=_parse_float(r"VO2max:\s*([0-9]+(?:\.[0-9]+)?)", text),
    )


def _parse_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def _parse_pace(text: str) -> float | None:
    """« Threshold Pace: 4:52 /km » → 292.0 (secondes par km)."""
    match = re.search(r"Threshold Pace:\s*(\d+):(\d{2})", text)
    return float(int(match.group(1)) * 60 + int(match.group(2))) if match else None


class CorosAthleteProvider:
    """Implémente le port `AthleteProvider`."""

    def __init__(self, client: MCPToolClient | None = None) -> None:
        self._client: MCPToolClient = client or CorosClient()

    async def get_athlete_profile(self) -> AthleteProfile:
        try:
            text = await self._client.call_tool(_FITNESS_TOOL, {})
        except Exception:
            # Toute panne COROS (identifiants, réseau, outil) → dégradation gracieuse.
            return AthleteProfile()
        return parse_fitness_overview(text)
