"""Tests du service de calibration : ingestion idempotente/incrémentale, compute, stores nuls."""

from datetime import date

from app.db.calibration import NullActivityRepository, NullCalibrationStore
from app.db.read_models import CalibrationStatus
from app.domain.models import ActivitySummary, AthleteProfile, CalibrationProfile
from app.services.calibration_service import CalibrationService


class _FakeWeather:
    async def historical_daily_temps(
        self, lat: float, lon: float, start: date, end: date
    ) -> dict[date, float]:
        return {}


def _activity(label: str, ts: int) -> ActivitySummary:
    return ActivitySummary(
        label_id=label,
        sport_type=100,
        start_timestamp=ts,
        activity_date=date(2026, 6, 1),
        distance_km=10.0,
        duration_s=3600,
    )


class _FakeProvider:
    def __init__(self, activities: list[ActivitySummary]) -> None:
        self._activities = activities

    async def list_activities(
        self, *, since: int | None = None, sport_codes: list[int] | None = None
    ) -> list[ActivitySummary]:
        return [a for a in self._activities if since is None or a.start_timestamp > since]


class _FakeRepo:
    def __init__(self) -> None:
        self.store: dict[str, ActivitySummary] = {}

    async def upsert(self, activities: list[ActivitySummary]) -> int:
        new = [a for a in activities if a.label_id not in self.store]
        for a in new:
            self.store[a.label_id] = a
        return len(new)

    async def last_synced_timestamp(self) -> int | None:
        return max((a.start_timestamp for a in self.store.values()), default=None)

    async def all_activities(self) -> list[ActivitySummary]:
        return list(self.store.values())

    async def set_weather(self, temps: dict[str, float]) -> int:
        return len(temps)

    async def status(self) -> CalibrationStatus:
        return CalibrationStatus(
            activity_count=len(self.store),
            first_activity_date=None,
            last_activity_date=None,
            last_synced_at=None,
            trail_count=0,
            calibration_computed_at=None,
        )


class _FakeAthlete:
    async def get_athlete_profile(self) -> AthleteProfile:
        return AthleteProfile(threshold_pace_sec_per_km=300.0)


class _FakeStore:
    def __init__(self) -> None:
        self.saved: CalibrationProfile | None = None

    async def load(self) -> CalibrationProfile | None:
        return self.saved

    async def save(self, profile: CalibrationProfile) -> None:
        self.saved = profile


def _service(provider: _FakeProvider, repo: _FakeRepo) -> tuple[CalibrationService, _FakeStore]:
    store = _FakeStore()
    service = CalibrationService(provider, repo, _FakeAthlete(), store, _FakeWeather())
    return service, store


async def test_backfill_then_incremental_is_idempotent() -> None:
    provider = _FakeProvider([_activity("a", 100), _activity("b", 200)])
    repo = _FakeRepo()
    service, _ = _service(provider, repo)

    first = await service.ingest(incremental=False)
    assert (first.fetched, first.inserted) == (2, 2)

    # Relance incrémentale : rien de nouveau (curseur = 200).
    again = await service.ingest(incremental=True)
    assert (again.fetched, again.inserted) == (0, 0)


async def test_incremental_picks_up_new_activity() -> None:
    activities = [_activity("a", 100), _activity("b", 200)]
    provider = _FakeProvider(activities)
    repo = _FakeRepo()
    service, _ = _service(provider, repo)
    await service.ingest(incremental=False)

    activities.append(_activity("c", 300))
    result = await service.ingest(incremental=True)
    assert (result.fetched, result.inserted) == (1, 1)
    assert set(repo.store) == {"a", "b", "c"}


async def test_refresh_computes_and_saves_profile() -> None:
    provider = _FakeProvider([_activity("a", 100), _activity("b", 200)])
    repo = _FakeRepo()
    service, store = _service(provider, repo)

    ingested, profile = await service.refresh(incremental=False)
    assert ingested.inserted == 2
    assert profile.sample_count == 2
    assert profile.computed_at is not None
    # Le snapshot est persisté pour être relu sur le chemin /strategy.
    assert store.saved is profile


async def test_null_stores_degrade_gracefully() -> None:
    assert await NullCalibrationStore().load() is None
    await NullCalibrationStore().save(CalibrationProfile())  # no-op, ne lève pas

    repo = NullActivityRepository()
    assert await repo.upsert([_activity("a", 100)]) == 0
    assert await repo.last_synced_timestamp() is None
    assert await repo.all_activities() == []
    status = await repo.status()
    assert status.activity_count == 0
    assert status.calibration_computed_at is None
