"""Préparation des données de visualisation (fonctions pures, testables sans Streamlit).

Le profil de dénivelé est reconstruit par cumul des pentes par km (`gradient_pct`),
la réponse `/strategy` ne renvoyant que la stratégie. La courbe d'allure vient des km_plans.
"""

from app.db.read_models import RunSummary
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


def history_rows(runs: list[RunSummary]) -> list[Row]:
    """Lignes du tableau d'historique (une par run)."""
    rows: list[Row] = []
    for run in runs:
        pace = run.average_pace_sec_per_km
        pace_label = "—"
        if pace is not None:
            minutes, seconds = divmod(round(pace), 60)
            pace_label = f"{minutes}:{seconds:02d}/km"
        rows.append(
            {
                "Id": run.id,
                "Date": run.created_at.strftime("%Y-%m-%d %H:%M"),
                "Distance (km)": round(run.distance_km, 2),
                "Origine": "IA" if run.generated_by == "llm" else "Repli",
                "Allure moy.": pace_label,
                "Garde-fous": "OK" if run.guardrails_passed else "non",
                "Écart baseline %": run.deviation_vs_baseline_pct
                if run.deviation_vs_baseline_pct is not None
                else 0.0,
            }
        )
    return rows


def km_table_rows(strategy: PaceStrategy) -> list[Row]:
    """Lignes du tableau de restitution km/km (lisible + exportable CSV)."""
    rows: list[Row] = []
    for plan in strategy.km_plans:
        minutes, seconds = divmod(round(plan.target_pace_sec_per_km), 60)
        rows.append(
            {
                "Km": plan.km_index,
                "Allure": f"{minutes}:{seconds:02d}/km",
                "Pente %": round(plan.gradient_pct, 1),
                "Effort": plan.effort,
                "Note": plan.note or "",
            }
        )
    return rows
