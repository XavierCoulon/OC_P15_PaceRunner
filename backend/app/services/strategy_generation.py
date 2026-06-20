"""Génération de stratégie avec garde-fous, fallback baseline (G2) et métrique qualité (M4).

Enchaîne : appel LLM → vérification des garde-fous → si conforme, on recalcule les
totaux pour garantir la cohérence interne ; sinon (sortie aberrante ou panne LLM), on
renvoie la stratégie déterministe M1. La provenance (`generated_by`) reste fiable :
`llm` si la sortie LLM est acceptée, `baseline` en cas de fallback. Chaque run journalise
une métrique qualité (origine, garde-fous, écart à la baseline, latence).
"""

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
from app.services.baseline_strategy import build_baseline_strategy
from app.services.strategy_guardrails import check_strategy
from app.services.strategy_quality import compute_quality, log_quality


async def generate_strategy(
    generator: StrategyGenerator,
    course: CourseProfile,
    race: RaceContext,
    athlete: AthleteProfile | None,
    weather: WeatherContext | None,
    surface: SurfaceContext | None,
) -> PaceStrategy:
    """Renvoie la stratégie LLM si elle passe les garde-fous, sinon le fallback baseline."""
    start = perf_counter()
    baseline = build_baseline_strategy(course, athlete)
    llm_guardrails_passed = False

    try:
        raw = await generator.generate(course, race, athlete, weather, surface)
        if check_strategy(raw, course, athlete):
            strategy = baseline
        else:
            strategy = recompute_totals(raw, course)
            llm_guardrails_passed = True
    except Exception:
        strategy = baseline

    latency_ms = (perf_counter() - start) * 1000
    log_quality(
        compute_quality(
            strategy, baseline, llm_guardrails_passed=llm_guardrails_passed, latency_ms=latency_ms
        )
    )
    return strategy


def recompute_totals(strategy: PaceStrategy, course: CourseProfile) -> PaceStrategy:
    """Recalcule temps estimé et allure moyenne depuis les allures km (ne fait pas confiance
    à l'arithmétique du LLM)."""
    distances = [segment.distance_km for segment in course.segments]
    total_time = sum(
        plan.target_pace_sec_per_km * dist
        for plan, dist in zip(strategy.km_plans, distances, strict=True)
    )
    average_pace = total_time / course.distance_km
    return strategy.model_copy(
        update={
            "estimated_time_sec": round(total_time, 1),
            "average_pace_sec_per_km": round(average_pace, 1),
        }
    )
