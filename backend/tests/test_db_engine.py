"""Tests de la couche base : normalisation d'URL + garde sans configuration."""

import pytest

from app.db.engine import DatabaseNotConfiguredError, get_engine, to_asyncpg_url


def test_to_asyncpg_url_converts_scheme_and_drops_query() -> None:
    assert to_asyncpg_url("postgresql://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"
    assert to_asyncpg_url("postgres://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"
    assert (
        to_asyncpg_url("postgresql://u:p@host/db?sslmode=require&channel_binding=require")
        == "postgresql+asyncpg://u:p@host/db"
    )


def test_get_engine_raises_without_database_url() -> None:
    get_engine.cache_clear()
    with pytest.raises(DatabaseNotConfiguredError):
        get_engine()
    get_engine.cache_clear()
