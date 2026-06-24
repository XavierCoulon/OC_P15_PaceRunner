"""Génération de stratégie avec garde-fous, fallback baseline (G2) et métrique qualité (M4).

Enchaîne : appel LLM → vérification des garde-fous → si conforme, on recalcule les
totaux pour garantir la cohérence interne ; sinon (sortie aberrante ou panne LLM), on
renvoie la stratégie déterministe M1. La provenance (`generated_by`) reste fiable :
`llm` si la sortie LLM est acceptée, `baseline` en cas de fallback. Chaque run journalise
une métrique qualité (origine, garde-fous, écart à la baseline, latence).
"""

from dataclasses import dataclass
from time import perf_counter

from app.domain.models import (
    AthleteProfile,
    CourseProfile,
    PaceStrategy,
    RaceContext,
    SurfaceContext,
    WeatherContext,
)
from app.domain.ports import StrategyGenerator
from app.services.baseline_strategy import build_baseline_strategy, effort_from_gradient
from app.services.strategy_guardrails import check_strategy
from app.services.strategy_quality import StrategyQuality, compute_quality, log_quality


@dataclass(frozen=True)
class GenerationOutcome:
    """Stratégie retenue et sa métrique qualité (journalisable)."""

    strategy: PaceStrategy
    quality: StrategyQuality


async def generate_strategy(
    generator: StrategyGenerator,
    course: CourseProfile,
    race: RaceContext,
    athlete: AthleteProfile | None,
    weather: WeatherContext | None,
    surface: SurfaceContext | None,
) -> GenerationOutcome:
    """Renvoie la stratégie LLM si elle passe les garde-fous, sinon le fallback baseline."""
    start = perf_counter()
    baseline = build_baseline_strategy(course, athlete, weather)
    llm_guardrails_passed = False

    try:
        raw = await generator.generate(course, race, athlete, weather, surface, baseline=baseline)
        if check_strategy(raw, course, athlete):
            strategy = baseline
        else:
            strategy = recompute_totals(raw, course)
            llm_guardrails_passed = True
    except Exception:
        strategy = baseline

    latency_ms = (perf_counter() - start) * 1000
    quality = compute_quality(
        strategy, baseline, llm_guardrails_passed=llm_guardrails_passed, latency_ms=latency_ms
    )
    log_quality(quality)
    return GenerationOutcome(strategy=strategy, quality=quality)


async def generate_autonomous(
    generator: StrategyGenerator,
    course: CourseProfile,
    race: RaceContext,
    athlete: AthleteProfile | None,
    weather: WeatherContext | None,
    surface: SurfaceContext | None,
) -> PaceStrategy:
    """Stratégie LLM **autonome et brute** : pas de baseline, **aucun garde-fou ni repli**.

    Sert à mesurer le modèle seul (cf. #74). On recalcule seulement les totaux (l'arithmétique
    LLM n'est pas fiable) sans toucher aux allures. Toute panne/sortie inexploitable se propage.
    """
    raw = await generator.generate(
        course, race, athlete, weather, surface, baseline=None, autonomous=True
    )
    strategy = raw.model_copy(update={"generated_by": "llm_autonomous"})
    if len(strategy.km_plans) == len(course.segments):
        strategy = _recompute_totals_only(strategy, course)
    return strategy


def _recompute_totals_only(strategy: PaceStrategy, course: CourseProfile) -> PaceStrategy:
    """Recalcule temps total + allure moyenne depuis les allures km, sans modifier les km_plans."""
    distances = [segment.distance_km for segment in course.segments]
    total_time = sum(
        plan.target_pace_sec_per_km * dist
        for plan, dist in zip(strategy.km_plans, distances, strict=True)
    )
    return strategy.model_copy(
        update={
            "estimated_time_sec": round(total_time, 1),
            "average_pace_sec_per_km": round(total_time / course.distance_km, 1),
        }
    )


def recompute_totals(strategy: PaceStrategy, course: CourseProfile) -> PaceStrategy:
    """Normalise la sortie LLM : effort recalculé depuis la pente (côté serveur), puis temps estimé
    et allure moyenne recalculés depuis les allures km (l'arithmétique LLM n'est pas fiable)."""
    distances = [segment.distance_km for segment in course.segments]
    km_plans = [
        plan.model_copy(update={"effort": effort_from_gradient(plan.gradient_pct)})
        for plan in strategy.km_plans
    ]
    total_time = sum(
        plan.target_pace_sec_per_km * dist for plan, dist in zip(km_plans, distances, strict=True)
    )
    average_pace = total_time / course.distance_km
    return strategy.model_copy(
        update={
            "km_plans": km_plans,
            "estimated_time_sec": round(total_time, 1),
            "average_pace_sec_per_km": round(average_pace, 1),
        }
    )
