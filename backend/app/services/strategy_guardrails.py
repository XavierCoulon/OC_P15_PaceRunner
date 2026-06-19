"""Garde-fous métier sur une stratégie d'allure (sortie LLM).

Vérifie la cohérence physiologique et logique avant d'accepter une stratégie générée :
nombre de kilomètres, allures dans des bornes plausibles (absolues et relatives à l'allure
seuil), et cohérence effort/pente (monter doit être plus lent que descendre). Renvoie la
liste des violations (vide = conforme). La décision de fallback est prise par l'appelant.
"""

from statistics import mean

from app.domain.models import AthleteProfile, CourseProfile, PaceStrategy

# Bornes absolues d'allure (s/km) : ~2:00 (élite) à ~20:00 (marche).
_ABS_MIN_PACE = 120.0
_ABS_MAX_PACE = 1200.0

# Bornes relatives à l'allure seuil.
_THRESHOLD_MIN_FACTOR = 0.6
_THRESHOLD_MAX_FACTOR = 2.5

# Seuils de pente (%) pour distinguer montée / descente.
_UPHILL_PCT = 1.0
_DOWNHILL_PCT = -1.0


def check_strategy(
    strategy: PaceStrategy, course: CourseProfile, athlete: AthleteProfile | None
) -> list[str]:
    """Renvoie la liste des violations des garde-fous (vide si la stratégie est conforme)."""
    reasons: list[str] = []

    if len(strategy.km_plans) != len(course.segments):
        reasons.append(
            f"nombre de km ({len(strategy.km_plans)}) != segments du parcours "
            f"({len(course.segments)})"
        )

    paces = [p.target_pace_sec_per_km for p in strategy.km_plans]
    if any(not (_ABS_MIN_PACE <= pace <= _ABS_MAX_PACE) for pace in paces):
        reasons.append("allure hors bornes absolues (2:00–20:00 /km)")

    threshold = athlete.threshold_pace_sec_per_km if athlete is not None else None
    if threshold is not None:
        low, high = _THRESHOLD_MIN_FACTOR * threshold, _THRESHOLD_MAX_FACTOR * threshold
        if any(not (low <= pace <= high) for pace in paces):
            reasons.append("allure incohérente avec l'allure seuil")

    uphill = [p.target_pace_sec_per_km for p in strategy.km_plans if p.gradient_pct > _UPHILL_PCT]
    downhill = [
        p.target_pace_sec_per_km for p in strategy.km_plans if p.gradient_pct < _DOWNHILL_PCT
    ]
    if uphill and downhill and mean(uphill) <= mean(downhill):
        reasons.append("montée pas plus lente que descente (effort/pente incohérent)")

    return reasons
