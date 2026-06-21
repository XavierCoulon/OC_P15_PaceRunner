"""Garde-fous métier sur une stratégie d'allure (sortie LLM).

Vérifie la cohérence physiologique et logique avant d'accepter une stratégie générée :
nombre de kilomètres, allures dans des bornes plausibles (absolues et relatives à l'allure
seuil), et cohérence effort/pente (monter doit être plus lent que descendre). Renvoie la
liste des violations (vide = conforme). La décision de fallback est prise par l'appelant.
"""

from statistics import mean

from app.domain.models import AthleteProfile, CourseProfile, PaceStrategy
from app.services.baseline_strategy import build_baseline_strategy

# Bornes absolues d'allure (s/km) : ~2:00 (élite) à ~20:00 (marche).
_ABS_MIN_PACE = 120.0
_ABS_MAX_PACE = 1200.0

# Bornes relatives à l'allure seuil. Borne haute large : en haute montagne (murs +20%),
# l'allure réaliste (power-hiking) atteint ~3× le seuil ; la cohérence fine est assurée
# par le garde-fou d'écart à la baseline grade-adjusted.
_THRESHOLD_MIN_FACTOR = 0.6
_THRESHOLD_MAX_FACTOR = 4.0

# Seuils de pente (%) pour distinguer montée / descente.
_UPHILL_PCT = 1.0
_DOWNHILL_PCT = -1.0

# Écart max par km vs la baseline grade-adjusted (sinon le LLM ignore la pente).
_MAX_KM_DEVIATION = 0.35


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

    # Cohérence avec la baseline grade-adjusted : le LLM ne doit pas « lisser » la pente.
    if len(strategy.km_plans) == len(course.segments):
        baseline = build_baseline_strategy(course, athlete)
        for llm_km, base_km in zip(strategy.km_plans, baseline.km_plans, strict=True):
            ref = base_km.target_pace_sec_per_km
            if abs(llm_km.target_pace_sec_per_km - ref) / ref > _MAX_KM_DEVIATION:
                reasons.append("allure trop éloignée de la baseline grade-adjusted (pente ignorée)")
                break

    return reasons
