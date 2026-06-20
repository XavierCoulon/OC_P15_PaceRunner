"""Connexion asynchrone à la base (Neon Postgres via asyncpg).

Neon fournit une URL `postgresql://…?sslmode=require` ; SQLAlchemy async attend
`postgresql+asyncpg://…` et asyncpg ne comprend pas le paramètre `sslmode`. On normalise
donc l'URL (driver + suppression des query params) et on force le SSL côté `connect_args`.
"""

from collections.abc import AsyncIterator
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


class DatabaseNotConfiguredError(RuntimeError):
    """`DATABASE_URL` est absent de la configuration."""


def to_asyncpg_url(url: str) -> str:
    """Normalise une URL Postgres pour le driver asyncpg (sans query params)."""
    parts = urlsplit(url)
    netloc = parts.netloc
    path = parts.path
    return urlunsplit(("postgresql+asyncpg", netloc, path, "", ""))


@lru_cache
def get_engine() -> AsyncEngine:
    database_url = get_settings().database_url
    if not database_url:
        raise DatabaseNotConfiguredError("DATABASE_URL absent.")
    return create_async_engine(
        to_asyncpg_url(database_url),
        connect_args={"ssl": True},  # Neon exige TLS
        pool_pre_ping=True,
    )


@lru_cache
def session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI : fournit une session asynchrone."""
    async with session_factory()() as session:
        yield session


async def ping() -> bool:
    """Vérifie la connectivité (SELECT 1)."""
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True
