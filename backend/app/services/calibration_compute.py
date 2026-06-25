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
    return CalibrationProfile(
        computed_at=_utcnow_naive(),
        sample_count=len(activities),
        distance_factors=distance_factors,
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
    trend = profile.fitness_trend
    if trend is not None:
        if trend >= 1.1:
            parts.append(f"charge d'entraînement récente en hausse (ACWR {trend:.2f})")
        elif trend <= 0.9:
            parts.append(f"charge récente en baisse, plutôt fraîche (ACWR {trend:.2f})")
        else:
            parts.append(f"forme stable (ACWR {trend:.2f})")
    return " ; ".join(parts) if parts else None
