"""Stratégie d'allure déterministe (baseline, sans IA).

Sert à la fois de **référence** de comparaison et de **fallback** quand le LLM échoue
(cf. ADR-1). Principe : partir de l'allure seuil COROS, l'ajuster à la distance de course,
à la **pente** de chaque kilomètre (*grade-adjusted pace*), à la **fraîcheur** du jour et
aux **conditions météo** (chaleur, vent, pluie).
"""

from app.domain.models import (
    AthleteProfile,
    CalibrationProfile,
    CourseProfile,
    KmPlan,
    PaceStrategy,
    WeatherContext,
)

# Allure de repli si l'allure seuil COROS est indisponible (6:00/km).
_DEFAULT_THRESHOLD_PACE = 360.0

# Borne supérieure « au-delà du marathon » (sentinelle, JSON-compatible contrairement à inf).
LONG_BIN_KM = 9999.0

# Facteurs d'allure de course par tranche de distance (l'allure seuil ≈ effort ~1 h).
# Génériques par défaut ; la calibration (#76, axe A) peut les remplacer par tes meilleurs efforts.
DISTANCE_BINS: tuple[tuple[float, float], ...] = (
    (5.0, 0.97),  # ≤ 5 km : un peu plus rapide que le seuil
    (10.0, 1.00),  # ≤ 10 km : ~ allure seuil
    (21.1, 1.05),  # ≤ semi
    (42.2, 1.12),  # ≤ marathon
    (LONG_BIN_KM, 1.18),  # au-delà du marathon
)

# Coût énergétique de la course selon la pente (Minetti et al., 2002, J/kg/m).
# Le facteur d'allure = coût(pente) / coût(plat) → fortement non-linéaire (cf. G3).
_FLAT_COST = 3.6
# Plafonne le gain en descente : Minetti minimise le coût métabolique, mais en course réelle
# le freinage limite la vitesse → on borne le gain à ~10 % (vs ~22 % pour le Minetti pur).
_DOWNHILL_FLOOR = 0.90

# Fraîcheur : récupération basse → allure plus prudente.
_FRESHNESS_MAX_PENALTY = 0.10  # +10 % au pire (récupération nulle)

# Météo : ralentissement réaliste (chaleur dominante, vent, pluie).
_HEAT_THRESHOLD_C = 20.0  # au-delà, la chaleur pénalise
_HEAT_PER_DEG = 0.006  # +0,6 %/°C au-dessus du seuil
_WIND_THRESHOLD_KMH = 25.0  # vent fort à partir de ~25 km/h
_WIND_PER_KMH = 0.002  # +0,2 %/km/h au-dessus du seuil
_RAIN_THRESHOLD_MM = 1.0
_RAIN_PENALTY = 0.01  # +1 % sous la pluie (prudence)
_MAX_WEATHER_PENALTY = 0.20  # plafond cumulé +20 %

# Seuils de pente (%) pour le label d'effort.
_HARD_PCT = 3.0
_EASY_PCT = -3.0


def _weather_factor(
    weather: WeatherContext | None, calibration: CalibrationProfile | None = None
) -> float:
    """Facteur de ralentissement dû aux conditions (1.0 = pas d'effet).

    La pénalité chaleur utilise la **sensibilité perso** (#76, axe B) si calibrée, sinon la
    constante générique de littérature.
    """
    if weather is None:
        return 1.0
    heat_threshold = _HEAT_THRESHOLD_C
    heat_per_deg = _HEAT_PER_DEG
    if calibration is not None and calibration.heat_coeff_per_deg is not None:
        heat_per_deg = calibration.heat_coeff_per_deg
        if calibration.heat_threshold_c is not None:
            heat_threshold = calibration.heat_threshold_c
    penalty = 0.0
    if weather.temperature_c is not None and weather.temperature_c > heat_threshold:
        penalty += (weather.temperature_c - heat_threshold) * heat_per_deg
    if weather.wind_speed_kmh is not None and weather.wind_speed_kmh > _WIND_THRESHOLD_KMH:
        penalty += (weather.wind_speed_kmh - _WIND_THRESHOLD_KMH) * _WIND_PER_KMH
    if weather.precipitation_mm is not None and weather.precipitation_mm > _RAIN_THRESHOLD_MM:
        penalty += _RAIN_PENALTY
    return 1.0 + min(penalty, _MAX_WEATHER_PENALTY)


def _race_pace_factor(
    distance_km: float, bins: tuple[tuple[float, float], ...] = DISTANCE_BINS
) -> float:
    for max_km, factor in bins:
        if distance_km <= max_km:
            return factor
    return bins[-1][1]


def _distance_bins(
    calibration: CalibrationProfile | None,
) -> tuple[tuple[float, float], ...]:
    """Tranches de distance perso (axe A) si calibrées, sinon les facteurs génériques."""
    if calibration is not None and calibration.distance_factors:
        return tuple((float(up), float(f)) for up, f in calibration.distance_factors)
    return DISTANCE_BINS


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


def build_baseline_strategy(
    course: CourseProfile,
    athlete: AthleteProfile | None,
    weather: WeatherContext | None = None,
    calibration: CalibrationProfile | None = None,
) -> PaceStrategy:
    """Construit une `PaceStrategy` déterministe (profil + forme athlète + météo).

    Si `calibration.distance_factors` est fourni (axe A, #76), la décroissance allure↔distance
    vient des **meilleurs efforts réels** du coureur au lieu des facteurs génériques ; l'allure
    seuil COROS reste l'ancre.
    """
    threshold = _DEFAULT_THRESHOLD_PACE
    recovery: float | None = None
    if athlete is not None:
        if athlete.threshold_pace_sec_per_km is not None:
            threshold = athlete.threshold_pace_sec_per_km
        recovery = athlete.recovery_pct

    bins = _distance_bins(calibration)
    base_pace = threshold * _race_pace_factor(course.distance_km, bins)
    freshness = _freshness_factor(recovery)
    weather_factor = _weather_factor(weather, calibration)

    km_plans: list[KmPlan] = []
    total_time = 0.0
    for segment in course.segments:
        grade_factor = _grade_factor(segment.gradient_pct)
        pace = base_pace * freshness * weather_factor * grade_factor
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
        pace = base_pace * freshness * weather_factor
        total_time = pace * course.distance_km
        km_plans.append(
            KmPlan(
                km_index=1, target_pace_sec_per_km=round(pace, 1), effort="steady", gradient_pct=0.0
            )
        )

    average_pace = total_time / course.distance_km
    recovery_note = f", récup {recovery:.0f}%" if recovery is not None else ""
    weather_note = f", météo +{(weather_factor - 1) * 100:.0f}%" if weather_factor > 1.0 else ""
    calib_note = (
        " · distance calibrée sur tes meilleurs efforts"
        if calibration is not None and calibration.distance_factors
        else ""
    )
    summary = (
        f"Baseline déterministe — allure seuil {_format_pace(threshold)}/km "
        f"ajustée à la distance, à la pente{recovery_note}{weather_note}{calib_note}."
    )
    return PaceStrategy(
        distance_km=course.distance_km,
        estimated_time_sec=round(total_time, 1),
        average_pace_sec_per_km=round(average_pace, 1),
        km_plans=km_plans,
        summary=summary,
        generated_by="baseline",
    )
