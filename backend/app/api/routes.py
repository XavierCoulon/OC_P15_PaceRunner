"""Routes de l'API.

- `GET /health` : sonde publique.
- `GET /athlete` : protégé (Bearer). Vérifie la connexion COROS → renvoie l'`AthleteProfile`.
- `POST /strategy` : protégé (Bearer). Pipeline complet — upload GPX + date/heure → `PaceStrategy`
  (profil + altitudes + COROS + météo → LLM avec garde-fous et fallback baseline).
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.adapters.coros_athlete import CorosAthleteProvider
from app.adapters.gpx_parser import GpxParseError
from app.adapters.llm_openai import OpenAICompatibleStrategyGenerator
from app.adapters.open_meteo import OpenMeteoWeatherProvider
from app.adapters.open_topo_data import OpenTopoDataProvider
from app.adapters.prediction_repo import NullPredictionRepository, SqlPredictionRepository
from app.api.security import require_api_token
from app.config import get_settings
from app.db.history import HistoryReader, NullHistoryReader, SqlHistoryReader
from app.db.read_models import RunDetail, RunStats, RunSummary
from app.domain.models import (
    AthleteProfile,
    CourseSummary,
    RaceContext,
    StrategyResponse,
)
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


def get_history_reader() -> HistoryReader:
    """Lecture du journal en base si configurée, sinon vide."""
    if get_settings().database_url:
        return SqlHistoryReader()
    return NullHistoryReader()


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
    response_model=StrategyResponse,
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
) -> StrategyResponse:
    """Pipeline complet : GPX + date/heure → stratégie + contexte (profil, COROS, météo)."""
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
        result = await build_strategy(
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

    return StrategyResponse(
        strategy=result.strategy,
        course=CourseSummary(
            distance_km=result.course.distance_km,
            elevation_gain_m=result.course.elevation_gain_m,
            elevation_loss_m=result.course.elevation_loss_m,
            start_lat=result.course.start_lat,
            start_lon=result.course.start_lon,
            segments=result.course.segments,
        ),
        athlete=result.athlete,
        weather=result.weather,
    )


@router.get(
    "/history",
    response_model=list[RunSummary],
    dependencies=[Depends(require_api_token)],
)
async def list_history(
    reader: Annotated[HistoryReader, Depends(get_history_reader)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunSummary]:
    """Liste paginée des stratégies générées (plus récentes d'abord)."""
    return await reader.list_runs(limit=limit, offset=offset)


@router.get(
    "/history/{run_id}",
    response_model=RunDetail,
    dependencies=[Depends(require_api_token)],
)
async def get_history(
    run_id: int,
    reader: Annotated[HistoryReader, Depends(get_history_reader)],
) -> RunDetail:
    """Détail d'un run (snapshots + stratégie complète)."""
    detail = await reader.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run introuvable.")
    return detail


@router.get(
    "/stats",
    response_model=RunStats,
    dependencies=[Depends(require_api_token)],
)
async def get_stats(
    reader: Annotated[HistoryReader, Depends(get_history_reader)],
) -> RunStats:
    """KPIs agrégés du journal (monitoring)."""
    return await reader.compute_stats()
