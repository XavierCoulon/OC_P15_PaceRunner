"""Page Données COROS (bloc 1, prérequis) — récupération/rafraîchissement de l'historique.

Permet de constituer (backfill) puis maintenir à jour (incrémental) la base de courses COROS
qui nourrit la calibration. Tant qu'aucune donnée n'est présente, la génération de stratégie
(page d'accueil) est bloquée. Affiche une visualisation chiffrée de ce qui est en base.
"""

import pandas as pd
import streamlit as st

from api_client import BackendError, fetch_calibration_status, refresh_calibration

_DIST_LABEL = {5.0: "≤ 5 km", 10.0: "≤ 10 km", 21.1: "Semi", 42.2: "Marathon", 9999.0: "Ultra"}


def _fmt_pace(seconds_per_km: float) -> str:
    minutes, secs = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{secs:02d}"


st.set_page_config(page_title="Données COROS — PaceRunner", page_icon="📥", layout="wide")

st.title("📥 Données COROS")
st.caption(
    "Récupère ton historique de courses COROS (prérequis à la génération de stratégie). "
    "Le premier import peut durer ; ensuite, l'incrémental ne récupère que les nouveautés."
)

try:
    status = fetch_calibration_status()
except BackendError as exc:
    st.error(str(exc))
    st.stop()

col_run, col_full = st.columns([3, 1])
with col_run:
    refresh = st.button("🔄 Récupérer / Rafraîchir mes données COROS", type="primary")
with col_full:
    full = st.checkbox("Backfill complet", value=status.activity_count == 0)

if refresh:
    try:
        with st.spinner("📥 Récupération des courses COROS…"):
            result = refresh_calibration(incremental=not full)
    except BackendError as exc:
        st.error(str(exc))
        st.stop()
    st.success(
        f"{result.inserted} nouvelle(s) course(s) ajoutée(s) "
        f"({result.fetched} remontée(s) par COROS)."
    )
    status = result.status

st.subheader("📊 Données en base")
if status.activity_count == 0:
    st.info("Aucune donnée — lance une première récupération ci-dessus.")
else:
    cols = st.columns(4)
    cols[0].metric("Courses", status.activity_count)
    period = (
        f"{status.first_activity_date:%d/%m/%Y} → {status.last_activity_date:%d/%m/%Y}"
        if status.first_activity_date and status.last_activity_date
        else "—"
    )
    cols[1].metric("Période couverte", period)
    cols[2].metric("Courses trail", status.trail_count)
    cols[3].metric(
        "Dernière synchro",
        f"{status.last_synced_at:%d/%m %H:%M}" if status.last_synced_at else "—",
    )
    if status.calibration_computed_at:
        st.caption(f"🧮 Calibration calculée le {status.calibration_computed_at:%d/%m/%Y %H:%M}.")
    else:
        st.caption("🧮 Calibration pas encore calculée — clique sur « Rafraîchir » ci-dessus.")

cal = status.calibration
if cal is not None and cal.computed_at is not None:
    st.subheader("🎯 Ce qui personnalise ta stratégie")
    st.caption(f"Calculé sur {cal.sample_count} courses analysées.")

    if cal.anchor_pace_sec_per_km and cal.distance_factors:
        st.markdown(
            f"**Allures de référence par distance** "
            f"(ancrées sur ton allure seuil COROS {_fmt_pace(cal.anchor_pace_sec_per_km)} /km, "
            f"calibrées sur tes meilleurs efforts) :"
        )
        rows = [
            {
                "Distance": _DIST_LABEL.get(upper, f"≤ {upper:.0f} km"),
                "Allure de référence": f"{_fmt_pace(cal.anchor_pace_sec_per_km * factor)} /km",
                "vs seuil": f"{(factor - 1) * 100:+.0f} %",
            }
            for upper, factor in cal.distance_factors
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.caption("Allures de référence : données insuffisantes → facteurs génériques.")

    cols = st.columns(2)
    heat = (
        f"+{cal.heat_coeff_per_deg * 100:.1f} %/°C au-delà de {cal.heat_threshold_c:.0f} °C"
        if cal.heat_coeff_per_deg is not None
        else "générique (peu de jours chauds)"
    )
    cols[0].metric("🌡️ Sensibilité à la chaleur", heat)
    trend = cal.fitness_trend
    if trend is None:
        trend_txt = "—"
    elif trend >= 1.1:
        trend_txt = f"{trend:.2f} ↗ en hausse"
    elif trend <= 0.9:
        trend_txt = f"{trend:.2f} ↘ allégée"
    else:
        trend_txt = f"{trend:.2f} → stable"
    cols[1].metric("📈 Charge récente (ACWR)", trend_txt)
