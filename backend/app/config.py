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

    # Sécurité API (cf. D4) — token Bearer attendu sur les endpoints protégés
    api_token: SecretStr | None = None

    # Secrets externes
    hf_token: SecretStr | None = None
    coros_refresh_token: SecretStr | None = None
    database_url: str | None = None

    # Sources & LLM — valeurs par défaut surchargeables
    coros_mcp_url: str = "https://mcpeu.coros.com/mcp"
    open_topo_data_url: str = "https://api.opentopodata.org/v1"
    open_topo_data_dataset: str = "aster30m"
    llm_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    http_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    """Retourne l'instance de configuration (mise en cache)."""
    return Settings()
