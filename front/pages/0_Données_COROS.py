"""Page Données COROS (bloc 1, prérequis) — récupération/rafraîchissement de l'historique.

Permet de constituer (backfill) puis maintenir à jour (incrémental) la base de courses COROS
qui nourrit la calibration. Tant qu'aucune donnée n'est présente, la génération de stratégie
(page d'accueil) est bloquée. Affiche une visualisation chiffrée de ce qui est en base.
"""

import streamlit as st

from api_client import BackendError, fetch_calibration_status, refresh_calibration

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
    cols[2].metric("Échantillons trail", status.trail_sample_count)
    cols[3].metric(
        "Dernière synchro",
        f"{status.last_synced_at:%d/%m %H:%M}" if status.last_synced_at else "—",
    )
    if status.calibration_computed_at:
        st.caption(f"🧮 Calibration calculée le {status.calibration_computed_at:%d/%m/%Y %H:%M}.")
    else:
        st.caption("🧮 Calibration pas encore calculée (à venir : personnalisation des allures).")
