"""Stockage durable des tokens COROS (rotation du refresh token).

COROS fait tourner le refresh token à chaque refresh : il faut donc persister le
nouveau token. L'access_token durant ~30 jours, on ne rafraîchit que lorsqu'il expire.
Implémentation fichier (local) ; un backend durable (Neon) sera câblé en phase N.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

_EXPIRY_MARGIN_SECONDS = 300


class CorosTokens(BaseModel):
    """Tokens COROS persistés."""

    access_token: str
    refresh_token: str
    expires_at: datetime

    def is_expired(self) -> bool:
        """Vrai si l'access_token est expiré (avec une marge de sécurité)."""
        return datetime.now(UTC) >= self.expires_at - timedelta(seconds=_EXPIRY_MARGIN_SECONDS)


class TokenStore(Protocol):
    """Port : charge/sauve les tokens COROS."""

    def load(self) -> CorosTokens | None: ...

    def save(self, tokens: CorosTokens) -> None: ...


class FileTokenStore:
    """Stockage fichier JSON (mono-utilisateur, local)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> CorosTokens | None:
        if not self._path.exists():
            return None
        try:
            return CorosTokens.model_validate_json(self._path.read_text())
        except (ValueError, OSError):
            return None

    def save(self, tokens: CorosTokens) -> None:
        self._path.write_text(tokens.model_dump_json())
