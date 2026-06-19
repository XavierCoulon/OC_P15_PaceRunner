"""Orchestrateur du pipeline complet (H1).

Assemble, dans l'ordre déterministe (ADR-1) : parsing GPX → nettoyage des altitudes →
enrichissements (forme COROS, météo, surface) → génération LLM avec garde-fous et
fallback baseline. Les providers dégradent gracieusement : seule une erreur de parsing
GPX interrompt le pipeline (renvoyée à l'appelant).
"""

from app.adapters.gpx_parser import parse_gpx
from app.domain.models import PaceStrategy, RaceContext
from app.domain.ports import (
    AthleteProvider,
    ElevationProvider,
    StrategyGenerator,
    SurfaceProvider,
    WeatherProvider,
)
from app.services.strategy_generation import generate_strategy


async def build_strategy(
    gpx_content: str,
    race: RaceContext,
    *,
    elevation: ElevationProvider,
    athlete_provider: AthleteProvider,
    weather: WeatherProvider,
    generator: StrategyGenerator,
    surface: SurfaceProvider | None = None,
) -> PaceStrategy:
    """Exécute le pipeline complet et renvoie la stratégie d'allure.

    Lève `GpxParseError` si le GPX est illisible (les autres étapes sont tolérantes).
    """
    course = parse_gpx(gpx_content)
    course = await elevation.clean_elevations(course)

    athlete = await athlete_provider.get_athlete_profile()
    weather_ctx = await weather.get_weather(course.start_lat, course.start_lon, race.race_datetime)
    surface_ctx = await surface.get_surface(course) if surface is not None else None

    return await generate_strategy(generator, course, race, athlete, weather_ctx, surface_ctx)
