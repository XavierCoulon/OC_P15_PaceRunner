"""Client HTTP du front vers le backend PaceRunner.

Appelle `POST /strategy` (multipart, Bearer) et valide la réponse contre le schéma
`PaceStrategy` du backend (contrat partagé). Traduit les échecs en `BackendError`
porteurs d'un message lisible pour l'UI.
"""

import httpx

from app.config import get_settings
from app.domain.models import StrategyResponse

_TIMEOUT_SECONDS = 180.0


class BackendError(Exception):
    """Échec d'appel au backend, avec message destiné à l'utilisateur."""


def generate_strategy(
    *, gpx_bytes: bytes, filename: str, race_datetime_iso: str, goal: str
) -> StrategyResponse:
    settings = get_settings()
    token = settings.api_token.get_secret_value() if settings.api_token else ""
    url = f"{settings.backend_url}/strategy"
    files = {"gpx": (filename, gpx_bytes, "application/gpx+xml")}
    data = {"race_datetime": race_datetime_iso, "goal": goal}
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = httpx.post(
            url, files=files, data=data, headers=headers, timeout=_TIMEOUT_SECONDS
        )
    except httpx.RequestError as exc:
        raise BackendError(f"Backend injoignable ({exc}).") from exc

    if response.status_code == 401:
        raise BackendError("Authentification refusée — vérifie le token API.")
    if response.status_code == 422:
        detail = _detail(response)
        raise BackendError(f"Fichier GPX invalide : {detail}")
    if response.status_code != 200:
        raise BackendError(f"Erreur backend (HTTP {response.status_code}).")

    try:
        return StrategyResponse.model_validate(response.json())
    except ValueError as exc:
        raise BackendError("Réponse du backend invalide.") from exc


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", ""))
    except ValueError:
        return ""
