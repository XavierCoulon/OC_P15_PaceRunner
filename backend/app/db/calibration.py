"""Persistance de la calibration (#76) : activités COROS + snapshot de profil.

- `SqlCalibrationStore` / `NullCalibrationStore` : implémentent le port `CalibrationStore`
  (lecture/écriture du `CalibrationProfile` précalculé).
- `SqlActivityRepository` / `NullActivityRepository` : upsert idempotent des résumés de course,
  curseur d'ingestion incrémentale et état pour `GET /calibration`.

Suit le pattern de `db/history.py` : variante SQL (Neon) + variante nulle (base non configurée).
"""

from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from app.db.engine import session_factory
from app.db.models import CalibrationSnapshot, CorosActivity
from app.db.read_models import CalibrationStatus
from app.domain.models import ActivitySummary, CalibrationProfile


class ActivityRepository(Protocol):
    async def upsert(self, activities: list[ActivitySummary]) -> int: ...
    async def last_synced_timestamp(self) -> int | None: ...
    async def all_activities(self) -> list[ActivitySummary]: ...
    async def status(self) -> CalibrationStatus: ...


class SqlCalibrationStore:
    """Implémente `CalibrationStore` : lit/écrit le dernier `CalibrationProfile` en base."""

    async def load(self) -> CalibrationProfile | None:
        async with session_factory()() as session:
            row = (
                await session.execute(
                    select(CalibrationSnapshot)
                    .order_by(col(CalibrationSnapshot.computed_at).desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return CalibrationProfile.model_validate(row.profile) if row is not None else None

    async def save(self, profile: CalibrationProfile) -> None:
        snapshot = CalibrationSnapshot(
            sample_count=profile.sample_count,
            profile=profile.model_dump(mode="json"),
        )
        async with session_factory()() as session:
            session.add(snapshot)
            await session.commit()


class NullCalibrationStore:
    """Implémente `CalibrationStore` sans base (dégradation gracieuse → pas de calibration)."""

    async def load(self) -> CalibrationProfile | None:
        return None

    async def save(self, profile: CalibrationProfile) -> None:
        return None


class SqlActivityRepository:
    """Persiste les résumés de course (upsert idempotent) et expose l'état d'ingestion."""

    async def upsert(self, activities: list[ActivitySummary]) -> int:
        """Insère les nouvelles courses (conflit sur `label_id` ignoré). Renvoie le nb inséré."""
        if not activities:
            return 0
        incoming = {a.label_id for a in activities}
        # model_dump() (objets Python, pas JSON) : la colonne Date attend un `date`, pas une str.
        rows = [a.model_dump() for a in activities]
        statement = (
            insert(CorosActivity).values(rows).on_conflict_do_nothing(index_elements=["label_id"])
        )
        async with session_factory()() as session:
            existing = set(
                (
                    await session.execute(
                        select(col(CorosActivity.label_id)).where(
                            col(CorosActivity.label_id).in_(incoming)
                        )
                    )
                )
                .scalars()
                .all()
            )
            await session.execute(statement)
            await session.commit()
        return len(incoming - existing)

    async def last_synced_timestamp(self) -> int | None:
        async with session_factory()() as session:
            return (
                await session.execute(select(func.max(CorosActivity.start_timestamp)))
            ).scalar_one_or_none()

    async def all_activities(self) -> list[ActivitySummary]:
        async with session_factory()() as session:
            rows = (await session.execute(select(CorosActivity))).scalars().all()
        return [
            ActivitySummary(
                label_id=row.label_id,
                sport_type=row.sport_type,
                start_timestamp=row.start_timestamp,
                activity_date=row.activity_date,
                distance_km=row.distance_km,
                duration_s=row.duration_s,
                avg_pace_sec_per_km=row.avg_pace_sec_per_km,
                avg_hr=row.avg_hr,
                start_lat=row.start_lat,
                start_lon=row.start_lon,
                location=row.location,
                elevation_gain_m=row.elevation_gain_m,
            )
            for row in rows
        ]

    async def status(self) -> CalibrationStatus:
        async with session_factory()() as session:
            count, first_date, last_date, last_synced, trail = (
                await session.execute(
                    select(
                        func.count(),
                        func.min(CorosActivity.activity_date),
                        func.max(CorosActivity.activity_date),
                        func.max(CorosActivity.created_at),
                        func.count().filter(col(CorosActivity.streams_fetched)),
                    )
                )
            ).one()
            computed_at = (
                await session.execute(select(func.max(CalibrationSnapshot.computed_at)))
            ).scalar_one_or_none()
        return CalibrationStatus(
            activity_count=count,
            first_activity_date=first_date,
            last_activity_date=last_date,
            last_synced_at=last_synced,
            trail_sample_count=trail,
            calibration_computed_at=computed_at,
        )


class NullActivityRepository:
    """Variante sans base : aucune persistance, état vide."""

    async def upsert(self, activities: list[ActivitySummary]) -> int:
        return 0

    async def last_synced_timestamp(self) -> int | None:
        return None

    async def all_activities(self) -> list[ActivitySummary]:
        return []

    async def status(self) -> CalibrationStatus:
        return CalibrationStatus(
            activity_count=0,
            first_activity_date=None,
            last_activity_date=None,
            last_synced_at=None,
            trail_sample_count=0,
            calibration_computed_at=None,
        )
