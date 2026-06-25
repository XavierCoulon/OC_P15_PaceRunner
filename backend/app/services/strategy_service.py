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
    CalibrationProfile,
    CourseProfile,
    GenerationMode,
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
    generate_raw,
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
    """Une variante à comparer : libellé + modèle + générateur + mode de prompt."""

    label: str
    model: str
    generator: StrategyGenerator
    mode: GenerationMode


@dataclass(frozen=True)
class EngineResult:
    """Stratégie brute d'une variante (ou l'erreur rencontrée)."""

    label: str
    model: str
    mode: GenerationMode
    strategy: PaceStrategy | None
    error: str | None


@dataclass(frozen=True)
class ComparisonResult:
    """Reco ancrée (production) + baseline (référence) + moteurs autonomes comparés (cf. #74)."""

    course: CourseProfile
    athlete: AthleteProfile | None
    weather: WeatherContext | None
    baseline: PaceStrategy
    recommended: PaceStrategy
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
    calibration: CalibrationProfile | None = None,
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

    outcome = await generate_strategy(
        generator, course, race, athlete, weather_ctx, surface_ctx, calibration
    )

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
    recommended_generator: StrategyGenerator,
    surface: SurfaceProvider | None = None,
    calibration: CalibrationProfile | None = None,
) -> ComparisonResult:
    """Enrichit une seule fois le contexte, produit la **reco ancrée** (production) puis compare
    la baseline aux moteurs LLM autonomes (#74).

    La reco ancrée passe par les garde-fous + repli baseline (tactique bornée + narratif). Chaque
    moteur de comparaison génère en mode **autonome brut** (sans baseline, ni garde-fou, ni repli).
    """
    course = parse_gpx(gpx_content)
    course = await elevation.clean_elevations(course)
    athlete = await athlete_provider.get_athlete_profile()
    weather_ctx = await weather.get_weather(course.start_lat, course.start_lon, race.race_datetime)
    surface_ctx = await surface.get_surface(course) if surface is not None else None

    baseline = build_baseline_strategy(course, athlete, weather_ctx, calibration)
    recommended = (
        await generate_strategy(
            recommended_generator, course, race, athlete, weather_ctx, surface_ctx, calibration
        )
    ).strategy

    results: list[EngineResult] = []
    for engine in engines:
        strategy: PaceStrategy | None = None
        error: str | None = None
        try:
            strategy = await generate_raw(
                engine.generator,
                course,
                race,
                athlete,
                weather_ctx,
                surface_ctx,
                engine.mode,
                calibration,
            )
        except Exception as exc:  # mode brut : pas de repli, on remonte l'échec de la variante
            error = f"{type(exc).__name__}: {exc}"
        results.append(
            EngineResult(
                label=engine.label,
                model=engine.model,
                mode=engine.mode,
                strategy=strategy,
                error=error,
            )
        )

    return ComparisonResult(
        course=course,
        athlete=athlete,
        weather=weather_ctx,
        baseline=baseline,
        recommended=recommended,
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
