"""Génération de stratégie avec garde-fous et fallback baseline (G2).

Enchaîne : appel LLM → vérification des garde-fous → si conforme, on recalcule les
totaux pour garantir la cohérence interne ; sinon (sortie aberrante ou panne LLM), on
renvoie la stratégie déterministe M1. La provenance (`generated_by`) reste fiable :
`llm` si la sortie LLM est acceptée, `baseline` en cas de fallback.
"""

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


async def generate_strategy(
    generator: StrategyGenerator,
    course: CourseProfile,
    race: RaceContext,
    athlete: AthleteProfile | None,
    weather: WeatherContext | None,
    surface: SurfaceContext | None,
) -> PaceStrategy:
    """Renvoie la stratégie LLM si elle passe les garde-fous, sinon le fallback baseline."""
    try:
        strategy = await generator.generate(course, race, athlete, weather, surface)
    except Exception:
        return build_baseline_strategy(course, athlete)

    if check_strategy(strategy, course, athlete):
        return build_baseline_strategy(course, athlete)

    return _with_consistent_totals(strategy, course)


def _with_consistent_totals(strategy: PaceStrategy, course: CourseProfile) -> PaceStrategy:
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
