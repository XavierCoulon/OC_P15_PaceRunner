"""Configuration applicative centralisée (pydantic-settings).

Les secrets sont optionnels au démarrage afin de permettre les tests et le lancement
local sans configuration. Ils seront exigés par les fonctionnalités qui les consomment
(auth Bearer, LLM Hugging Face, base de données Neon, COROS).
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Paramètres chargés depuis l'environnement puis le fichier `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Général
    app_name: str = "PaceRunner"
    environment: str = "dev"

    # Front → backend (le front appelle l'API ; en prod combiné : localhost:8000)
    backend_url: str = "http://localhost:8000"
    # Carte du tracé (front) : token Mapbox pour le fond relief/satellite (optionnel)
    mapbox_token: SecretStr | None = None

    # Sécurité API (cf. D4) — token Bearer attendu sur les endpoints protégés
    api_token: SecretStr | None = None

    # Secrets externes
    hf_token: SecretStr | None = None
    coros_refresh_token: SecretStr | None = None
    database_url: str | None = None

    # Sources & LLM — valeurs par défaut surchargeables
    coros_mcp_url: str = "https://mcpeu.coros.com/mcp"
    coros_token_url: str = "https://mcpeu.coros.com/oauth2/token"
    coros_client_id: str | None = None
    coros_token_file: str = ".coros_token_store.json"
    open_topo_data_url: str = "https://api.opentopodata.org/v1"
    open_topo_data_dataset: str = "aster30m"
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_air_quality_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    climatology_years: int = 5
    http_timeout_seconds: float = 10.0

    # LLM — API OpenAI-compatible (Ollama local par défaut ; HF par config, cf. ADR-4)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3.1:8b"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 120.0


@lru_cache
def get_settings() -> Settings:
    """Retourne l'instance de configuration (mise en cache)."""
    return Settings()
