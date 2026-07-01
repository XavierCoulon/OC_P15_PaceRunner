"""Calcul de la calibration (#76, axes A & C) à partir de l'historique COROS.

Fonctions **pures** (testables sans base) : on agrège les `ActivitySummary` persistés en un
`CalibrationProfile`.

- **Axe A** — décroissance allure↔distance issue des **meilleurs efforts par tranche** (proxy
  d'allure de course, pas les footings). On divise par l'allure seuil COROS → des facteurs qui
  remplacent ceux, génériques, de la baseline. Le seuil reste l'ancre.
- **Axe C** — tendance de forme (ratio charge aiguë/chronique, ACWR). **Informative** : elle ne
  modifie pas les allures, elle nourrit seulement le résumé qualitatif du prompt.
"""

from datetime import UTC, date, datetime

from app.domain.models import ActivitySummary, CalibrationProfile
from app.services.baseline_strategy import DISTANCE_BINS

# Axe A — meilleurs efforts par tranche.
_EFFORT_WINDOW_DAYS = 540  # ~18 mois : la forme récente prime
_MIN_SAMPLES_PER_BIN = 4
_FACTOR_FLOOR = 0.80  # garde-fou : jamais plus rapide que 0,8 × seuil
_FACTOR_CEIL = 2.0

# Axe C — ACWR (acute:chronic workload ratio) sur la distance.
_ACUTE_DAYS = 28
_CHRONIC_DAYS = 84
_MIN_CHRONIC_RUNS = 4

# Axe B — sensibilité chaleur : pente du résidu d'allure vs (température − 20 °C).
_HEAT_THRESHOLD_C = 20.0
_MIN_HOT_SAMPLES = 8  # nb minimal de courses au-dessus du seuil pour fiabiliser la pente
_HEAT_COEFF_MAX = 0.03  # plafond de sécurité (3 %/°C)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _best_pace(paces: list[float]) -> float:
    """Allure « meilleurs efforts » : moyenne du quintile le plus rapide (au moins une course)."""
    ordered = sorted(paces)  # croissant : du plus rapide au plus lent
    k = max(1, len(ordered) // 5)
    return sum(ordered[:k]) / k


def _distance_factors(
    activities: list[ActivitySummary], threshold: float, today: date
) -> list[tuple[float, float]] | None:
    """Facteurs (borne_sup_km, facteur) par tranche : meilleurs efforts récents / seuil.

    Une tranche sans assez d'échantillons retombe sur son facteur générique. Renvoie `None`
    si aucune tranche n'a pu être calibrée (→ la baseline garde entièrement ses génériques).
    """
    factors: list[tuple[float, float]] = []
    lower = 0.0
    calibrated = False
    for upper, generic in DISTANCE_BINS:
        paces = [
            a.avg_pace_sec_per_km
            for a in activities
            if a.avg_pace_sec_per_km is not None
            and lower < a.distance_km <= upper
            and (today - a.activity_date).days <= _EFFORT_WINDOW_DAYS
        ]
        if len(paces) >= _MIN_SAMPLES_PER_BIN:
            factor = min(_FACTOR_CEIL, max(_FACTOR_FLOOR, _best_pace(paces) / threshold))
            calibrated = True
        else:
            factor = generic
        factors.append((upper, round(factor, 4)))
        lower = upper
    return factors if calibrated else None


def _pace_factor(distance_km: float, bins: tuple[tuple[float, float], ...]) -> float:
    for upper, factor in bins:
        if distance_km <= upper:
            return factor
    return bins[-1][1]


def _slope(points: list[tuple[float, float]]) -> float | None:
    """Pente d'une régression linéaire simple (moindres carrés). `None` si x sans variance."""
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    var_x = sum((x - mean_x) ** 2 for x, _ in points)
    if var_x <= 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return cov / var_x


def _heat_coeff(
    activities: list[ActivitySummary],
    threshold: float,
    distance_factors: list[tuple[float, float]] | None,
) -> float | None:
    """Sensibilité chaleur : pente du **résidu d'allure** vs (température − 20 °C).

    Résidu = (allure réelle − allure attendue) / attendue, l'attendue étant le seuil × le facteur
    de distance (perso si calibré, sinon générique). On régresse ce résidu contre l'excès de
    température au-dessus de 20 °C. Renvoie `None` (→ constante générique) si trop peu de jours
    chauds ou si la pente n'est pas positive (pas de preuve de pénalité chaleur).
    """
    bins = (
        tuple((float(up), float(f)) for up, f in distance_factors)
        if distance_factors
        else DISTANCE_BINS
    )
    points: list[tuple[float, float]] = []
    hot = 0
    for a in activities:
        if a.avg_pace_sec_per_km is None or a.weather_temperature_c is None:
            continue
        expected = threshold * _pace_factor(a.distance_km, bins)
        residual = (a.avg_pace_sec_per_km - expected) / expected
        excess = max(0.0, a.weather_temperature_c - _HEAT_THRESHOLD_C)
        points.append((excess, residual))
        if excess > 0:
            hot += 1
    if hot < _MIN_HOT_SAMPLES:
        return None
    slope = _slope(points)
    if slope is None or slope <= 0:
        return None
    return round(min(slope, _HEAT_COEFF_MAX), 5)


def _fitness_trend(activities: list[ActivitySummary], today: date) -> float | None:
    """ACWR : charge des 28 derniers jours / charge aiguë-équivalente sur 84 jours (distance)."""
    chronic = [a for a in activities if (today - a.activity_date).days < _CHRONIC_DAYS]
    if len(chronic) < _MIN_CHRONIC_RUNS:
        return None
    chronic_equiv = sum(a.distance_km for a in chronic) * _ACUTE_DAYS / _CHRONIC_DAYS
    if chronic_equiv <= 0:
        return None
    acute = sum(a.distance_km for a in activities if (today - a.activity_date).days < _ACUTE_DAYS)
    return round(acute / chronic_equiv, 2)


def compute_calibration(
    activities: list[ActivitySummary],
    threshold_pace_sec_per_km: float | None,
    today: date | None = None,
) -> CalibrationProfile:
    """Agrège l'historique en `CalibrationProfile` (axes A & C). Garde-fous → champs `None`."""
    today = today or datetime.now(UTC).date()
    distance_factors = (
        _distance_factors(activities, threshold_pace_sec_per_km, today)
        if threshold_pace_sec_per_km
        else None
    )
    heat_coeff = (
        _heat_coeff(activities, threshold_pace_sec_per_km, distance_factors)
        if threshold_pace_sec_per_km
        else None
    )
    return CalibrationProfile(
        computed_at=_utcnow_naive(),
        sample_count=len(activities),
        distance_factors=distance_factors,
        heat_coeff_per_deg=heat_coeff,
        heat_threshold_c=_HEAT_THRESHOLD_C if heat_coeff is not None else None,
        fitness_trend=_fitness_trend(activities, today),
    )


def calibration_note(profile: CalibrationProfile | None) -> str | None:
    """Résumé qualitatif (FR) destiné au prompt — pas de stats brutes à recombiner."""
    if profile is None:
        return None
    parts: list[str] = []
    if profile.distance_factors:
        parts.append(
            f"allures de référence calibrées sur tes meilleurs efforts "
            f"({profile.sample_count} courses analysées)"
        )
    if profile.heat_coeff_per_deg is not None:
        threshold_c = profile.heat_threshold_c or _HEAT_THRESHOLD_C
        parts.append(
            f"sensibilité à la chaleur mesurée "
            f"(+{profile.heat_coeff_per_deg * 100:.1f} %/°C au-delà de {threshold_c:.0f} °C)"
        )
    trend = profile.fitness_trend
    if trend is not None:
        if trend >= 1.1:
            parts.append(f"charge d'entraînement récente en hausse (ACWR {trend:.2f})")
        elif trend <= 0.9:
            parts.append(f"charge récente en baisse, plutôt fraîche (ACWR {trend:.2f})")
        else:
            parts.append(f"forme stable (ACWR {trend:.2f})")
    return " ; ".join(parts) if parts else None
