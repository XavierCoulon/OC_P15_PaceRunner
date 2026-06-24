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
class Engine:
    """Un moteur LLM à comparer (libellé + modèle + générateur)."""

    label: str
    model: str
    generator: StrategyGenerator


@dataclass(frozen=True)
class EngineResult:
    """Stratégie autonome brute d'un moteur (ou l'erreur rencontrée)."""

    label: str
    model: str
    strategy: PaceStrategy | None
    error: str | None


@dataclass(frozen=True)
class ComparisonResult:
    """Baseline (référence) + stratégies autonomes des moteurs comparés (cf. #74)."""

    course: CourseProfile
    athlete: AthleteProfile | None
    weather: WeatherContext | None
    baseline: PaceStrategy
    engines: list[EngineResult]


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
    engines: list[Engine],
    surface: SurfaceProvider | None = None,
) -> ComparisonResult:
    """Enrichit une seule fois le contexte, puis compare la baseline aux moteurs LLM (#74).

    Chaque moteur génère en mode **autonome brut** (sans baseline, sans garde-fou ni repli).
    Toute panne d'un moteur devient son `error` ; les autres colonnes restent disponibles.
    """
    course = parse_gpx(gpx_content)
    course = await elevation.clean_elevations(course)
    athlete = await athlete_provider.get_athlete_profile()
    weather_ctx = await weather.get_weather(course.start_lat, course.start_lon, race.race_datetime)
    surface_ctx = await surface.get_surface(course) if surface is not None else None

    baseline = build_baseline_strategy(course, athlete, weather_ctx)

    results: list[EngineResult] = []
    for engine in engines:
        strategy: PaceStrategy | None = None
        error: str | None = None
        try:
            strategy = await generate_autonomous(
                engine.generator, course, race, athlete, weather_ctx, surface_ctx
            )
        except Exception as exc:  # mode brut : pas de repli, on remonte l'échec du moteur
            error = f"{type(exc).__name__}: {exc}"
        results.append(
            EngineResult(label=engine.label, model=engine.model, strategy=strategy, error=error)
        )

    return ComparisonResult(
        course=course,
        athlete=athlete,
        weather=weather_ctx,
        baseline=baseline,
        engines=results,
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
