"""Service de calibration (#76) : ingestion de l'historique COROS + calcul du profil.

Hors du chemin de génération. `ingest()` récupère les résumés de course et les persiste (upsert
idempotent, incrémental borné par le dernier `start_timestamp`). `compute()` agrège les
courses en base en un `CalibrationProfile` (axes A & C) et le persiste. `refresh()` enchaîne
les deux : c'est ce qu'appelle l'endpoint admin.
"""

from dataclasses import dataclass

from app.adapters.coros_activities import RUN_SPORT_CODES
from app.db.calibration import ActivityRepository
from app.domain.models import ActivitySummary, CalibrationProfile
from app.domain.ports import (
    ActivityHistoryProvider,
    AthleteProvider,
    CalibrationStore,
    HistoricalWeatherProvider,
)
from app.services.calibration_compute import compute_calibration

# Arrondi des coordonnées pour regrouper les courses par lieu : 1 décimale (~11 km) suffit pour
# la température (régionale) et limite le nombre d'appels Open-Meteo (→ évite le rate-limiting).
_COORD_PRECISION = 1


@dataclass(frozen=True)
class IngestResult:
    """Bilan d'ingestion : nb de courses remontées par COROS et nb réellement insérées."""

    fetched: int
    inserted: int


class CalibrationService:
    """Orchestre ingestion + calcul de la calibration. Indépendant du chemin de génération."""

    def __init__(
        self,
        history_provider: ActivityHistoryProvider,
        activity_repo: ActivityRepository,
        athlete_provider: AthleteProvider,
        calibration_store: CalibrationStore,
        weather_provider: HistoricalWeatherProvider,
    ) -> None:
        self._history_provider = history_provider
        self._activity_repo = activity_repo
        self._athlete_provider = athlete_provider
        self._calibration_store = calibration_store
        self._weather_provider = weather_provider

    async def ingest(self, *, incremental: bool = True) -> IngestResult:
        """Récupère et persiste les courses. Idempotent (les doublons `label_id` sont ignorés)."""
        since = await self._activity_repo.last_synced_timestamp() if incremental else None
        activities = await self._history_provider.list_activities(
            since=since, sport_codes=RUN_SPORT_CODES
        )
        inserted = await self._activity_repo.upsert(activities)
        return IngestResult(fetched=len(activities), inserted=inserted)

    async def ingest_weather(self) -> int:
        """Joint la température ERA5 aux courses qui n'en ont pas (axe B).

        Regroupe par lieu (coordonnées arrondies) pour ne faire qu'un appel Open-Meteo par lieu
        sur toute la plage de dates, puis persiste la température par course. Best-effort.
        """
        activities = await self._activity_repo.all_activities()
        groups: dict[tuple[float, float], list[ActivitySummary]] = {}
        for a in activities:
            if a.weather_temperature_c is not None or a.start_lat is None or a.start_lon is None:
                continue
            key = (round(a.start_lat, _COORD_PRECISION), round(a.start_lon, _COORD_PRECISION))
            groups.setdefault(key, []).append(a)
        temps: dict[str, float] = {}
        for (lat, lon), group in groups.items():
            days = [a.activity_date for a in group]
            daily = await self._weather_provider.historical_daily_temps(
                lat, lon, min(days), max(days)
            )
            for a in group:
                temp = daily.get(a.activity_date)
                if temp is not None:
                    temps[a.label_id] = temp
        return await self._activity_repo.set_weather(temps)

    async def compute(self) -> CalibrationProfile:
        """Agrège les courses en base en un `CalibrationProfile` et le persiste (snapshot)."""
        activities = await self._activity_repo.all_activities()
        athlete = await self._athlete_provider.get_athlete_profile()
        profile = compute_calibration(activities, athlete.threshold_pace_sec_per_km)
        await self._calibration_store.save(profile)
        return profile

    async def refresh(self, *, incremental: bool = True) -> tuple[IngestResult, CalibrationProfile]:
        """Ingestion (courses + météo jointe) puis recalcul de la calibration."""
        ingested = await self.ingest(incremental=incremental)
        await self.ingest_weather()
        profile = await self.compute()
        return ingested, profile
