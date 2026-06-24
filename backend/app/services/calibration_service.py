"""Service de calibration (#76) : ingestion de l'historique COROS, hors chemin /strategy.

`ingest()` récupère les résumés de course via `ActivityHistoryProvider` et les persiste
(upsert idempotent). Le mode **incrémental** ne demande à COROS que les activités postérieures
au dernier `start_timestamp` connu ; le **backfill** (incremental=False) repart de zéro.

Le calcul du `CalibrationProfile` (les 4 axes) arrivera dans les phases suivantes (#78+).
"""

from dataclasses import dataclass

from app.adapters.coros_activities import RUN_SPORT_CODES
from app.db.calibration import ActivityRepository
from app.domain.ports import ActivityHistoryProvider


@dataclass(frozen=True)
class IngestResult:
    """Bilan d'ingestion : nb de courses remontées par COROS et nb réellement insérées."""

    fetched: int
    inserted: int


class CalibrationService:
    """Orchestre l'ingestion COROS → base. Indépendant du chemin de génération de stratégie."""

    def __init__(self, provider: ActivityHistoryProvider, repository: ActivityRepository) -> None:
        self._provider = provider
        self._repository = repository

    async def ingest(self, *, incremental: bool = True) -> IngestResult:
        """Récupère et persiste les courses. Idempotent (les doublons `label_id` sont ignorés)."""
        since = await self._repository.last_synced_timestamp() if incremental else None
        activities = await self._provider.list_activities(since=since, sport_codes=RUN_SPORT_CODES)
        inserted = await self._repository.upsert(activities)
        return IngestResult(fetched=len(activities), inserted=inserted)
