"""Métriques de qualité d'une stratégie (réutilisées par l'éval M3 et la journalisation M4)."""

from app.domain.models import AthleteProfile, CourseProfile, PaceStrategy
from app.services.strategy_guardrails import check_strategy


def guardrails_passed(
    strategy: PaceStrategy, course: CourseProfile, athlete: AthleteProfile | None
) -> bool:
    """Vrai si la stratégie respecte tous les garde-fous métier."""
    return not check_strategy(strategy, course, athlete)


def deviation_vs_baseline_pct(strategy: PaceStrategy, baseline: PaceStrategy) -> float:
    """Écart relatif (%) de l'allure moyenne entre une stratégie et la baseline."""
    base = baseline.average_pace_sec_per_km
    return round((strategy.average_pace_sec_per_km - base) / base * 100, 1)
