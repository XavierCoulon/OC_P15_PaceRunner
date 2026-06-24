"""Orchestrateur du pipeline complet (H1) + journalisation non bloquante (N3).

Assemble, dans l'ordre déterministe (ADR-1) : parsing GPX → nettoyage des altitudes →
enrichissements (forme COROS, météo, surface) → génération LLM avec garde-fous et
fallback baseline. Si un repository est fourni, chaque run est journalisé **sans bloquer**
la réponse (un échec d'écriture est seulement loggé).
"""

import hashlib
import logging
from dataclasses import dataclass

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
from app.services.baseline_strategy import build_baseline_strategy
from app.services.strategy_generation import (
    GenerationOutcome,
    generate_autonomous,
    generate_strategy,
)

_logger = logging.getLogger("pacerunner.journal")


@dataclass(frozen=True)
class PipelineResult:
    """Stratégie produite et le contexte consolidé qui l'a nourrie."""

    strategy: PaceStrategy
    course: CourseProfile
    athlete: AthleteProfile | None
    weather: WeatherContext | None
    surface: SurfaceContext | None


@dataclass(frozen=True)
class ComparisonResult:
    """Trois stratégies (baseline / ancrée / autonome brute) sur le même contexte (cf. #74)."""

    course: CourseProfile
    athlete: AthleteProfile | None
    weather: WeatherContext | None
    baseline: PaceStrategy
    anchored: PaceStrategy
    autonomous: PaceStrategy | None
    autonomous_error: str | None


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
) -> PipelineResult:
    """Exécute le pipeline complet et renvoie la stratégie + le contexte utilisé.

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
    return PipelineResult(
        strategy=outcome.strategy,
        course=course,
        athlete=athlete,
        weather=weather_ctx,
        surface=surface_ctx,
    )


async def build_comparison(
    gpx_content: str,
    race: RaceContext,
    *,
    elevation: ElevationProvider,
    athlete_provider: AthleteProvider,
    weather: WeatherProvider,
    generator: StrategyGenerator,
    surface: SurfaceProvider | None = None,
) -> ComparisonResult:
    """Enrichit une seule fois le contexte, puis produit les 3 stratégies à comparer (#74).

    `baseline` et `anchored` réutilisent le pipeline standard (garde-fous + repli). `autonomous`
    est la sortie LLM brute (sans garde-fous) ; toute panne devient `autonomous_error`.
    """
    course = parse_gpx(gpx_content)
    course = await elevation.clean_elevations(course)
    athlete = await athlete_provider.get_athlete_profile()
    weather_ctx = await weather.get_weather(course.start_lat, course.start_lon, race.race_datetime)
    surface_ctx = await surface.get_surface(course) if surface is not None else None

    baseline = build_baseline_strategy(course, athlete, weather_ctx)
    outcome = await generate_strategy(generator, course, race, athlete, weather_ctx, surface_ctx)

    autonomous: PaceStrategy | None = None
    autonomous_error: str | None = None
    try:
        autonomous = await generate_autonomous(
            generator, course, race, athlete, weather_ctx, surface_ctx
        )
    except Exception as exc:  # mode brut : on n'a pas de repli, on remonte l'échec
        autonomous_error = f"{type(exc).__name__}: {exc}"

    return ComparisonResult(
        course=course,
        athlete=athlete,
        weather=weather_ctx,
        baseline=baseline,
        anchored=outcome.strategy,
        autonomous=autonomous,
        autonomous_error=autonomous_error,
    )


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
