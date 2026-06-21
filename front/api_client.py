"""Client HTTP du front vers le backend PaceRunner.

Appelle `POST /strategy` (multipart, Bearer) et valide la réponse contre le schéma
`PaceStrategy` du backend (contrat partagé). Traduit les échecs en `BackendError`
porteurs d'un message lisible pour l'UI.
"""

from typing import Any

import httpx

from app.config import get_settings
from app.db.read_models import RunStats, RunSummary
from app.domain.models import StrategyResponse

_TIMEOUT_SECONDS = 180.0
_GET_TIMEOUT_SECONDS = 30.0


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


def fetch_history(*, limit: int = 20, offset: int = 0) -> list[RunSummary]:
    """Liste paginée des stratégies passées (`GET /history`)."""
    data = _get("/history", {"limit": limit, "offset": offset})
    try:
        return [RunSummary.model_validate(row) for row in data]
    except (ValueError, TypeError) as exc:
        raise BackendError("Réponse d'historique invalide.") from exc


def fetch_stats() -> RunStats:
    """KPIs agrégés du journal (`GET /stats`)."""
    data = _get("/stats", None)
    try:
        return RunStats.model_validate(data)
    except ValueError as exc:
        raise BackendError("Réponse de statistiques invalide.") from exc


def _get(path: str, params: dict[str, int] | None) -> Any:
    settings = get_settings()
    token = settings.api_token.get_secret_value() if settings.api_token else ""
    url = f"{settings.backend_url}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=_GET_TIMEOUT_SECONDS)
    except httpx.RequestError as exc:
        raise BackendError(f"Backend injoignable ({exc}).") from exc
    if response.status_code == 401:
        raise BackendError("Authentification refusée — vérifie le token API.")
    if response.status_code != 200:
        raise BackendError(f"Erreur backend (HTTP {response.status_code}).")
    return response.json()


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", ""))
    except ValueError:
        return ""
