"""AthleteProvider de test : double seedé sur un snapshot réel COROS (tests/offline)."""

from app.domain.models import AthleteProfile

# Snapshot observé via le spike : allure seuil 4:52/km (292 s), VO2max 45.
_DEFAULT = AthleteProfile(threshold_pace_sec_per_km=292.0, vo2max=45.0)


class CorosMockAthleteProvider:
    """Implémente le port `AthleteProvider` sans appel réseau."""

    def __init__(self, profile: AthleteProfile | None = None) -> None:
        self._profile = profile or _DEFAULT

    async def get_athlete_profile(self) -> AthleteProfile:
        return self._profile
