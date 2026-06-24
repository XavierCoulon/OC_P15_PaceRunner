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
from app.adapters.gpx_parser import GpxParseError, parse_gpx
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
    CourseProfile,
    CourseSummary,
    RaceContext,
    RoutePoint,
    StrategyComparison,
    StrategyResponse,
    TrackPoint,
    WeatherContext,
)
from app.domain.ports import (
    AthleteProvider,
    ElevationProvider,
    PredictionRepository,
    StrategyGenerator,
    WeatherProvider,
)
from app.services.strategy_service import build_comparison, build_strategy

router = APIRouter()

_MAX_ROUTE_POINTS = 300


def sample_route(points: list[TrackPoint]) -> list[RoutePoint]:
    """Échantillonne le tracé pour la carte (≤ 300 points, départ et arrivée conservés)."""
    if not points:
        return []
    step = max(1, -(-len(points) // _MAX_ROUTE_POINTS))  # division plafond
    sampled = points[::step]
    if sampled[-1] is not points[-1]:
        sampled = [*sampled, points[-1]]
    return [RoutePoint(lat=p.lat, lon=p.lon) for p in sampled]


def _course_summary(course: CourseProfile) -> CourseSummary:
    return CourseSummary(
        distance_km=course.distance_km,
        elevation_gain_m=course.elevation_gain_m,
        elevation_loss_m=course.elevation_loss_m,
        elevation_source=course.elevation_source,
        raw_elevation_gain_m=course.raw_elevation_gain_m,
        raw_elevation_loss_m=course.raw_elevation_loss_m,
        start_lat=course.start_lat,
        start_lon=course.start_lon,
        segments=course.segments,
        route=sample_route(course.points),
    )


async def _read_gpx(gpx: UploadFile) -> str:
    raw = await gpx.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Fichier GPX non décodable (UTF-8 attendu).",
        ) from exc


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
) -> StrategyResponse:
    """Pipeline complet : GPX + date/heure → stratégie + contexte (profil, COROS, météo)."""
    content = await _read_gpx(gpx)
    race = RaceContext(race_datetime=race_datetime)
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
        course=_course_summary(result.course),
        athlete=result.athlete,
        weather=result.weather,
    )


@router.post(
    "/strategy/compare",
    response_model=StrategyComparison,
    dependencies=[Depends(require_api_token)],
)
async def compare_strategies(
    gpx: Annotated[UploadFile, File(description="Fichier GPX du parcours.")],
    race_datetime: Annotated[datetime, Form(description="Date/heure de la course (ISO 8601).")],
    elevation: Annotated[ElevationProvider, Depends(get_elevation_provider)],
    athlete_provider: Annotated[AthleteProvider, Depends(get_athlete_provider)],
    weather: Annotated[WeatherProvider, Depends(get_weather_provider)],
    generator: Annotated[StrategyGenerator, Depends(get_strategy_generator)],
) -> StrategyComparison:
    """Compare 3 stratégies sur le même contexte : baseline, LLM ancré, LLM autonome brut (#74)."""
    content = await _read_gpx(gpx)
    race = RaceContext(race_datetime=race_datetime)
    try:
        result = await build_comparison(
            content,
            race,
            elevation=elevation,
            athlete_provider=athlete_provider,
            weather=weather,
            generator=generator,
        )
    except GpxParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return StrategyComparison(
        course=_course_summary(result.course),
        athlete=result.athlete,
        weather=result.weather,
        baseline=result.baseline,
        anchored=result.anchored,
        autonomous=result.autonomous,
        autonomous_error=result.autonomous_error,
    )


@router.post(
    "/profile",
    response_model=CourseSummary,
    dependencies=[Depends(require_api_token)],
)
async def get_profile(
    gpx: Annotated[UploadFile, File(description="Fichier GPX du parcours.")],
    elevation: Annotated[ElevationProvider, Depends(get_elevation_provider)],
) -> CourseSummary:
    """Aperçu rapide : GPX → profil (distance, D+, segments, tracé) — sans la stratégie."""
    content = await _read_gpx(gpx)
    try:
        course = parse_gpx(content)
    except GpxParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    course = await elevation.clean_elevations(course)
    return _course_summary(course)


@router.get(
    "/weather",
    response_model=WeatherContext,
    dependencies=[Depends(require_api_token)],
)
async def get_weather_at(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    race_datetime: Annotated[datetime, Query(description="Date/heure de la course (ISO 8601).")],
    weather: Annotated[WeatherProvider, Depends(get_weather_provider)],
) -> WeatherContext:
    """Conditions au point donné pour la date/heure (dégradation gracieuse)."""
    return await weather.get_weather(lat, lon, race_datetime)


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
