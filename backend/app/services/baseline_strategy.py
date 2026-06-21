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

# Coût énergétique de la course selon la pente (Minetti et al., 2002, J/kg/m).
# Le facteur d'allure = coût(pente) / coût(plat) → fortement non-linéaire (cf. G3).
_FLAT_COST = 3.6
# Plafonne le gain en descente : Minetti minimise le coût métabolique, mais en course réelle
# le freinage limite la vitesse → on borne le gain à ~10 % (vs ~22 % pour le Minetti pur).
_DOWNHILL_FLOOR = 0.90

# Fraîcheur : récupération basse → allure plus prudente.
_FRESHNESS_MAX_PENALTY = 0.10  # +10 % au pire (récupération nulle)

# Seuils de pente (%) pour le label d'effort.
_HARD_PCT = 3.0
_EASY_PCT = -3.0


def _race_pace_factor(distance_km: float) -> float:
    for max_km, factor in _DISTANCE_FACTORS:
        if distance_km <= max_km:
            return factor
    return _LONG_FACTOR


def _grade_factor(gradient_pct: float) -> float:
    """Facteur d'allure dû à la pente (grade-adjusted pace, modèle de Minetti)."""
    i = gradient_pct / 100.0
    cost = 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + _FLAT_COST
    return max(cost / _FLAT_COST, _DOWNHILL_FLOOR)


def _freshness_factor(recovery_pct: float | None) -> float:
    if recovery_pct is None:
        return 1.0
    return 1.0 + _FRESHNESS_MAX_PENALTY * (100.0 - recovery_pct) / 100.0


def effort_from_gradient(gradient_pct: float) -> str:
    """Label d'effort déduit de la pente (réutilisé pour recalculer l'effort côté serveur)."""
    if gradient_pct >= _HARD_PCT:
        return "hard"
    if gradient_pct <= _EASY_PCT:
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
                effort=effort_from_gradient(segment.gradient_pct),
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
