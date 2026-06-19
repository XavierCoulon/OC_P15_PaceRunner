"""AthleteProvider de test : double seedé sur un snapshot réel COROS (tests/offline)."""

from app.domain.models import AthleteProfile

# Snapshot réel observé : seuil 4:52/km (292 s), VO2max 45, récup 87 %, poids 71,2 kg.
_DEFAULT = AthleteProfile(
    threshold_pace_sec_per_km=292.0,
    vo2max=45.0,
    recovery_pct=87.0,
    recovery_status="Moderate training recommended",
    weight_kg=71.2,
)


class CorosMockAthleteProvider:
    """Implémente le port `AthleteProvider` sans appel réseau."""

    def __init__(self, profile: AthleteProfile | None = None) -> None:
        self._profile = profile or _DEFAULT

    async def get_athlete_profile(self) -> AthleteProfile:
        return self._profile
