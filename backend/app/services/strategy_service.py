"""Orchestrateur du pipeline complet (H1) + journalisation non bloquante (N3).

Assemble, dans l'ordre déterministe (ADR-1) : parsing GPX → nettoyage des altitudes →
enrichissements (forme COROS, météo, surface) → génération LLM avec garde-fous et
fallback baseline. Si un repository est fourni, chaque run est journalisé **sans bloquer**
la réponse (un échec d'écriture est seulement loggé).
"""

import hashlib
import logging

from app.adapters.gpx_parser import parse_gpx
from app.domain.models import (
    AthleteProfile,
    CourseProfile,
    PaceStrategy,
    RaceContext,
    SurfaceContext,
    WeatherContext,
)
from app.domain.ports import (
    AthleteProvider,
    ElevationProvider,
    PredictionRepository,
    StrategyGenerator,
    SurfaceProvider,
    WeatherProvider,
)
from app.services.strategy_generation import GenerationOutcome, generate_strategy

_logger = logging.getLogger("pacerunner.journal")


async def build_strategy(
    gpx_content: str,
    race: RaceContext,
    *,
    elevation: ElevationProvider,
    athlete_provider: AthleteProvider,
    weather: WeatherProvider,
    generator: StrategyGenerator,
    surface: SurfaceProvider | None = None,
    repository: PredictionRepository | None = None,
) -> PaceStrategy:
    """Exécute le pipeline complet et renvoie la stratégie d'allure.

    Lève `GpxParseError` si le GPX est illisible (les autres étapes sont tolérantes).
    """
    course = parse_gpx(gpx_content)
    gpx_hash = hashlib.sha256(gpx_content.encode("utf-8")).hexdigest()
    course = await elevation.clean_elevations(course)

    athlete = await athlete_provider.get_athlete_profile()
    weather_ctx = await weather.get_weather(course.start_lat, course.start_lon, race.race_datetime)
    surface_ctx = await surface.get_surface(course) if surface is not None else None

    outcome = await generate_strategy(generator, course, race, athlete, weather_ctx, surface_ctx)

    if repository is not None:
        await _journal(
            repository, gpx_hash, course, race, athlete, weather_ctx, surface_ctx, outcome
        )
    return outcome.strategy


async def _journal(
    repository: PredictionRepository,
    gpx_hash: str,
    course: CourseProfile,
    race: RaceContext,
    athlete: AthleteProfile | None,
    weather: WeatherContext | None,
    surface: SurfaceContext | None,
    outcome: GenerationOutcome,
) -> None:
    """Journalise le run sans bloquer : un échec d'écriture est loggé, pas propagé."""
    try:
        await repository.save_run(
            gpx_hash=gpx_hash,
            course=course,
            race=race,
            athlete=athlete,
            weather=weather,
            surface=surface,
            strategy=outcome.strategy,
            latency_ms=outcome.quality.latency_ms,
            guardrails_passed=outcome.quality.llm_guardrails_passed,
            deviation_vs_baseline_pct=outcome.quality.deviation_vs_baseline_pct,
        )
    except Exception as exc:  # journalisation best-effort
        _logger.warning("Échec de journalisation du run : %r", exc)
