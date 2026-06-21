"""Préparation des données de visualisation (fonctions pures, testables sans Streamlit).

Le profil de dénivelé est reconstruit par cumul des pentes par km (`gradient_pct`),
la réponse `/strategy` ne renvoyant que la stratégie. La courbe d'allure vient des km_plans.
"""

from app.domain.models import PaceStrategy

Row = dict[str, float | int | str]


def strategy_rows(strategy: PaceStrategy) -> list[Row]:
    """Une ligne par km : dénivelé cumulé, allure, label, effort, pente."""
    rows: list[Row] = []
    cumulative_elevation = 0.0
    for plan in strategy.km_plans:
        cumulative_elevation += plan.gradient_pct / 100.0 * 1000.0  # ≈ m gagnés sur ~1 km
        minutes, seconds = divmod(round(plan.target_pace_sec_per_km), 60)
        rows.append(
            {
                "km": plan.km_index,
                "elevation_m": round(cumulative_elevation, 1),
                "pace_sec": plan.target_pace_sec_per_km,
                "pace_label": f"{minutes}:{seconds:02d}",
                "effort": plan.effort,
                "gradient_pct": plan.gradient_pct,
            }
        )
    return rows
