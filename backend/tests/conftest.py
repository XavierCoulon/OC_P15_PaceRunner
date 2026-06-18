"""Fixtures partagées : isole les tests du fichier `.env` local du développeur."""

from collections.abc import Iterator

import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Désactive le chargement de `.env` et vide le cache de configuration.

    Garantit des tests déterministes quelles que soient les variables présentes en local.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
