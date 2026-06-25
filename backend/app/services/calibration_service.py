"""Service de calibration (#76) : ingestion de l'historique COROS + calcul du profil.

Hors chemin /strategy. `ingest()` récupère les résumés de course et les persiste (upsert
idempotent, incrémental borné par le dernier `start_timestamp`). `compute()` agrège les
courses en base en un `CalibrationProfile` (axes A & C) et le persiste. `refresh()` enchaîne
les deux : c'est ce qu'appelle l'endpoint admin.
"""

from dataclasses import dataclass

from app.adapters.coros_activities import RUN_SPORT_CODES
from app.db.calibration import ActivityRepository
from app.domain.models import CalibrationProfile
from app.domain.ports import ActivityHistoryProvider, AthleteProvider, CalibrationStore
from app.services.calibration_compute import compute_calibration


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
    ) -> None:
        self._history_provider = history_provider
        self._activity_repo = activity_repo
        self._athlete_provider = athlete_provider
        self._calibration_store = calibration_store

    async def ingest(self, *, incremental: bool = True) -> IngestResult:
        """Récupère et persiste les courses. Idempotent (les doublons `label_id` sont ignorés)."""
        since = await self._activity_repo.last_synced_timestamp() if incremental else None
        activities = await self._history_provider.list_activities(
            since=since, sport_codes=RUN_SPORT_CODES
        )
        inserted = await self._activity_repo.upsert(activities)
        return IngestResult(fetched=len(activities), inserted=inserted)

    async def compute(self) -> CalibrationProfile:
        """Agrège les courses en base en un `CalibrationProfile` et le persiste (snapshot)."""
        activities = await self._activity_repo.all_activities()
        athlete = await self._athlete_provider.get_athlete_profile()
        profile = compute_calibration(activities, athlete.threshold_pace_sec_per_km)
        await self._calibration_store.save(profile)
        return profile

    async def refresh(self, *, incremental: bool = True) -> tuple[IngestResult, CalibrationProfile]:
        """Ingestion puis recalcul de la calibration (appelé par l'endpoint de rafraîchissement)."""
        ingested = await self.ingest(incremental=incremental)
        profile = await self.compute()
        return ingested, profile
