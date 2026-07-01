"""Sécurité de l'API : authentification par token Bearer.

Dépendance FastAPI à attacher aux endpoints protégés (ex. `/strategy/generate`, `/history`).
`/health` reste public. Le token attendu provient de la configuration (`API_TOKEN`).
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def require_api_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Exige un en-tête `Authorization: Bearer <API_TOKEN>` valide."""
    expected = settings.api_token
    if expected is None:
        # Fail-safe : pas de token configuré → on refuse l'accès plutôt que de l'ouvrir.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentification non configurée",
        )
    provided = credentials.credentials if credentials is not None else ""
    # Comparaison à temps constant (anti timing-attack).
    if not secrets.compare_digest(provided, expected.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou absent",
            headers={"WWW-Authenticate": "Bearer"},
        )
