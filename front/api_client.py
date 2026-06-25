"""Client HTTP du front vers le backend PaceRunner.

Appelle `POST /strategy` (multipart, Bearer) et valide la réponse contre le schéma
`PaceStrategy` du backend (contrat partagé). Traduit les échecs en `BackendError`
porteurs d'un message lisible pour l'UI.
"""

from typing import Any

import httpx

from app.config import get_settings
from app.db.read_models import (
    CalibrationRefreshResult,
    CalibrationStatus,
    RunStats,
    RunSummary,
)
from app.domain.models import (
    AthleteProfile,
    CourseSummary,
    StrategyComparison,
    StrategyResponse,
    WeatherContext,
)

_TIMEOUT_SECONDS = 180.0
_REFRESH_TIMEOUT_SECONDS = 600.0
_GET_TIMEOUT_SECONDS = 30.0


class BackendError(Exception):
    """Échec d'appel au backend, avec message destiné à l'utilisateur."""


def generate_strategy(
    *, gpx_bytes: bytes, filename: str, race_datetime_iso: str
) -> StrategyResponse:
    settings = get_settings()
    token = settings.api_token.get_secret_value() if settings.api_token else ""
    url = f"{settings.backend_url}/strategy"
    files = {"gpx": (filename, gpx_bytes, "application/gpx+xml")}
    data = {"race_datetime": race_datetime_iso}
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


def _post_comparison(
    path: str, *, gpx_bytes: bytes, filename: str, race_datetime_iso: str
) -> StrategyComparison:
    """POST multipart renvoyant un `StrategyComparison` (endpoints generate / compare)."""
    settings = get_settings()
    token = settings.api_token.get_secret_value() if settings.api_token else ""
    url = f"{settings.backend_url}{path}"
    files = {"gpx": (filename, gpx_bytes, "application/gpx+xml")}
    data = {"race_datetime": race_datetime_iso}
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
        raise BackendError(f"Fichier GPX invalide : {_detail(response)}")
    if response.status_code != 200:
        raise BackendError(f"Erreur backend (HTTP {response.status_code}).")
    try:
        return StrategyComparison.model_validate(response.json())
    except ValueError as exc:
        raise BackendError("Réponse invalide.") from exc


def generate_plan(*, gpx_bytes: bytes, filename: str, race_datetime_iso: str) -> StrategyComparison:
    """« Générer » : reco ancrée DeepSeek + comparaison baseline vs DeepSeek CoT."""
    return _post_comparison(
        "/strategy/generate",
        gpx_bytes=gpx_bytes,
        filename=filename,
        race_datetime_iso=race_datetime_iso,
    )


def compare_strategies(
    *, gpx_bytes: bytes, filename: str, race_datetime_iso: str
) -> StrategyComparison:
    """« Comparer » : baseline vs llama3.1:8b autonome vs DeepSeek CoT (#74)."""
    return _post_comparison(
        "/strategy/compare",
        gpx_bytes=gpx_bytes,
        filename=filename,
        race_datetime_iso=race_datetime_iso,
    )


def fetch_profile(*, gpx_bytes: bytes, filename: str) -> CourseSummary:
    """Aperçu rapide du parcours (`POST /profile`) : profil + tracé, sans la stratégie."""
    settings = get_settings()
    token = settings.api_token.get_secret_value() if settings.api_token else ""
    url = f"{settings.backend_url}/profile"
    files = {"gpx": (filename, gpx_bytes, "application/gpx+xml")}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = httpx.post(url, files=files, headers=headers, timeout=_GET_TIMEOUT_SECONDS)
    except httpx.RequestError as exc:
        raise BackendError(f"Backend injoignable ({exc}).") from exc
    if response.status_code == 401:
        raise BackendError("Authentification refusée — vérifie le token API.")
    if response.status_code == 422:
        raise BackendError(f"Fichier GPX invalide : {_detail(response)}")
    if response.status_code != 200:
        raise BackendError(f"Erreur backend (HTTP {response.status_code}).")
    try:
        return CourseSummary.model_validate(response.json())
    except ValueError as exc:
        raise BackendError("Réponse de profil invalide.") from exc


def fetch_athlete() -> AthleteProfile:
    """Forme de l'athlète COROS (`GET /athlete`)."""
    data = _get("/athlete", None)
    try:
        return AthleteProfile.model_validate(data)
    except ValueError as exc:
        raise BackendError("Réponse athlète invalide.") from exc


def fetch_weather(*, lat: float, lon: float, race_datetime_iso: str) -> WeatherContext:
    """Conditions au point donné pour la date/heure (`GET /weather`)."""
    data = _get("/weather", {"lat": str(lat), "lon": str(lon), "race_datetime": race_datetime_iso})
    try:
        return WeatherContext.model_validate(data)
    except ValueError as exc:
        raise BackendError("Réponse météo invalide.") from exc


def fetch_history(*, limit: int = 20, offset: int = 0) -> list[RunSummary]:
    """Liste paginée des stratégies passées (`GET /history`)."""
    data = _get("/history", {"limit": str(limit), "offset": str(offset)})
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


def fetch_calibration_status() -> CalibrationStatus:
    """État des données COROS en base (`GET /calibration`) — prérequis de la génération."""
    data = _get("/calibration", None)
    try:
        return CalibrationStatus.model_validate(data)
    except ValueError as exc:
        raise BackendError("Réponse de calibration invalide.") from exc


def refresh_calibration(*, incremental: bool = True) -> CalibrationRefreshResult:
    """Déclenche l'ingestion COROS (`POST /calibration/refresh`). Long : backfill possible."""
    settings = get_settings()
    token = settings.api_token.get_secret_value() if settings.api_token else ""
    url = f"{settings.backend_url}/calibration/refresh"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"incremental": "true" if incremental else "false"}
    try:
        response = httpx.post(url, params=params, headers=headers, timeout=_REFRESH_TIMEOUT_SECONDS)
    except httpx.RequestError as exc:
        raise BackendError(f"Backend injoignable ({exc}).") from exc
    if response.status_code == 401:
        raise BackendError("Authentification refusée — vérifie le token API.")
    if response.status_code != 200:
        raise BackendError(f"Erreur backend (HTTP {response.status_code}).")
    try:
        return CalibrationRefreshResult.model_validate(response.json())
    except ValueError as exc:
        raise BackendError("Réponse de rafraîchissement invalide.") from exc


def _get(path: str, params: dict[str, str] | None) -> Any:
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
