"""Stratégie d'allure déterministe (baseline, sans IA).

Sert à la fois de **référence** de comparaison et de **fallback** quand le LLM échoue
(cf. ADR-1). Principe : partir de l'allure seuil COROS, l'ajuster à la distance de course,
à la **pente** de chaque kilomètre (*grade-adjusted pace*) et à la **fraîcheur** du jour.
"""

from app.domain.models import AthleteProfile, CourseProfile, KmPlan, PaceStrategy

# Allure de repli si l'allure seuil COROS est indisponible (6:00/km).
_DEFAULT_THRESHOLD_PACE = 360.0

# Facteur d'allure de course selon la distance (l'allure seuil ≈ effort ~1 h).
_DISTANCE_FACTORS: tuple[tuple[float, float], ...] = (
    (5.0, 0.97),  # ≤ 5 km : un peu plus rapide que le seuil
    (10.0, 1.00),  # ≤ 10 km : ~ allure seuil
    (21.1, 1.05),  # ≤ semi
    (42.2, 1.12),  # ≤ marathon
)
_LONG_FACTOR = 1.18  # au-delà du marathon

# Ajustement à la pente : montée ralentit, descente accélère (avec plancher).
_UPHILL_PER_PCT = 0.03
_DOWNHILL_PER_PCT = 0.02
_DOWNHILL_FLOOR = 0.90  # gain max de 10 % en descente

# Fraîcheur : récupération basse → allure plus prudente.
_FRESHNESS_MAX_PENALTY = 0.10  # +10 % au pire (récupération nulle)


def _race_pace_factor(distance_km: float) -> float:
    for max_km, factor in _DISTANCE_FACTORS:
        if distance_km <= max_km:
            return factor
    return _LONG_FACTOR


def _grade_factor(gradient_pct: float) -> float:
    if gradient_pct >= 0:
        return 1.0 + _UPHILL_PER_PCT * gradient_pct
    return max(1.0 + _DOWNHILL_PER_PCT * gradient_pct, _DOWNHILL_FLOOR)


def _freshness_factor(recovery_pct: float | None) -> float:
    if recovery_pct is None:
        return 1.0
    return 1.0 + _FRESHNESS_MAX_PENALTY * (100.0 - recovery_pct) / 100.0


def _effort(grade_factor: float) -> str:
    if grade_factor >= 1.08:
        return "hard"
    if grade_factor <= 0.97:
        return "easy"
    return "steady"


def _format_pace(pace_sec: float) -> str:
    minutes, seconds = divmod(round(pace_sec), 60)
    return f"{minutes}:{seconds:02d}"


def build_baseline_strategy(course: CourseProfile, athlete: AthleteProfile | None) -> PaceStrategy:
    """Construit une `PaceStrategy` déterministe à partir du profil et de la forme athlète."""
    threshold = _DEFAULT_THRESHOLD_PACE
    recovery: float | None = None
    if athlete is not None:
        if athlete.threshold_pace_sec_per_km is not None:
            threshold = athlete.threshold_pace_sec_per_km
        recovery = athlete.recovery_pct

    base_pace = threshold * _race_pace_factor(course.distance_km)
    freshness = _freshness_factor(recovery)

    km_plans: list[KmPlan] = []
    total_time = 0.0
    for segment in course.segments:
        grade_factor = _grade_factor(segment.gradient_pct)
        pace = base_pace * freshness * grade_factor
        total_time += pace * segment.distance_km
        km_plans.append(
            KmPlan(
                km_index=segment.km_index,
                target_pace_sec_per_km=round(pace, 1),
                effort=_effort(grade_factor),
                gradient_pct=segment.gradient_pct,
            )
        )

    if not km_plans:  # profil sans segmentation : un plan unique sur la distance
        pace = base_pace * freshness
        total_time = pace * course.distance_km
        km_plans.append(
            KmPlan(
                km_index=1, target_pace_sec_per_km=round(pace, 1), effort="steady", gradient_pct=0.0
            )
        )

    average_pace = total_time / course.distance_km
    recovery_note = f", récup {recovery:.0f}%" if recovery is not None else ""
    summary = (
        f"Baseline déterministe — allure seuil {_format_pace(threshold)}/km "
        f"ajustée à la distance, à la pente{recovery_note}."
    )
    return PaceStrategy(
        distance_km=course.distance_km,
        estimated_time_sec=round(total_time, 1),
        average_pace_sec_per_km=round(average_pace, 1),
        km_plans=km_plans,
        summary=summary,
        generated_by="baseline",
    )
