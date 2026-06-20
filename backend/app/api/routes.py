"""Routes de l'API.

- `GET /health` : sonde publique.
- `GET /athlete` : protégé (Bearer). Vérifie la connexion COROS → renvoie l'`AthleteProfile`.
- `POST /strategy` : protégé (Bearer). Pipeline complet — upload GPX + date/heure → `PaceStrategy`
  (profil + altitudes + COROS + météo → LLM avec garde-fous et fallback baseline).
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.adapters.coros_athlete import CorosAthleteProvider
from app.adapters.gpx_parser import GpxParseError
from app.adapters.llm_openai import OpenAICompatibleStrategyGenerator
from app.adapters.open_meteo import OpenMeteoWeatherProvider
from app.adapters.open_topo_data import OpenTopoDataProvider
from app.adapters.prediction_repo import NullPredictionRepository, SqlPredictionRepository
from app.api.security import require_api_token
from app.config import get_settings
from app.domain.models import AthleteProfile, PaceStrategy, RaceContext
from app.domain.ports import (
    AthleteProvider,
    ElevationProvider,
    PredictionRepository,
    StrategyGenerator,
    WeatherProvider,
)
from app.services.strategy_service import build_strategy

router = APIRouter()


def get_athlete_provider() -> AthleteProvider:
    """Fournit le provider COROS (surchargé dans les tests)."""
    return CorosAthleteProvider()


def get_elevation_provider() -> ElevationProvider:
    return OpenTopoDataProvider()


def get_weather_provider() -> WeatherProvider:
    return OpenMeteoWeatherProvider()


def get_strategy_generator() -> StrategyGenerator:
    return OpenAICompatibleStrategyGenerator()


def get_prediction_repository() -> PredictionRepository:
    """Journalise en base si DATABASE_URL est configuré, sinon no-op."""
    if get_settings().database_url:
        return SqlPredictionRepository()
    return NullPredictionRepository()


@router.get("/health")
def health() -> dict[str, str]:
    """Sonde de disponibilité (publique, utilisée par le smoke test et le déploiement)."""
    return {"status": "ok"}


@router.get(
    "/athlete",
    response_model=AthleteProfile,
    dependencies=[Depends(require_api_token)],
)
async def get_athlete(
    provider: Annotated[AthleteProvider, Depends(get_athlete_provider)],
) -> AthleteProfile:
    """Vérifie la connexion COROS et renvoie la forme de l'athlète.

    Si COROS est indisponible, renvoie un profil aux champs nuls (dégradation gracieuse).
    """
    return await provider.get_athlete_profile()


@router.post(
    "/strategy",
    response_model=PaceStrategy,
    dependencies=[Depends(require_api_token)],
)
async def create_strategy(
    gpx: Annotated[UploadFile, File(description="Fichier GPX du parcours.")],
    race_datetime: Annotated[datetime, Form(description="Date/heure de la course (ISO 8601).")],
    elevation: Annotated[ElevationProvider, Depends(get_elevation_provider)],
    athlete_provider: Annotated[AthleteProvider, Depends(get_athlete_provider)],
    weather: Annotated[WeatherProvider, Depends(get_weather_provider)],
    generator: Annotated[StrategyGenerator, Depends(get_strategy_generator)],
    repository: Annotated[PredictionRepository, Depends(get_prediction_repository)],
    goal: Annotated[str | None, Form(description="Objectif (optionnel).")] = None,
) -> PaceStrategy:
    """Exécute le pipeline complet : GPX + date/heure → stratégie d'allure km par km."""
    raw = await gpx.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Fichier GPX non décodable (UTF-8 attendu).",
        ) from exc

    race = RaceContext(race_datetime=race_datetime, goal=goal)
    try:
        return await build_strategy(
            content,
            race,
            elevation=elevation,
            athlete_provider=athlete_provider,
            weather=weather,
            generator=generator,
            repository=repository,
        )
    except GpxParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
