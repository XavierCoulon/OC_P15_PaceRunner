"""Page Historique — liste des stratégies générées (`GET /history`)."""

import pandas as pd
import streamlit as st

from api_client import BackendError, fetch_history
from viz import history_rows

st.set_page_config(page_title="Historique — PaceRunner", page_icon="📜", layout="wide")

st.title("📜 Historique des stratégies")
st.caption("Les stratégies générées, les plus récentes d'abord.")

limit = st.slider("Nombre de runs à afficher", min_value=5, max_value=100, value=20, step=5)

try:
    runs = fetch_history(limit=limit)
except BackendError as exc:
    runs = []
    st.error(str(exc))

if not runs:
    st.info("Aucune stratégie enregistrée pour l'instant.")
else:
    st.dataframe(pd.DataFrame(history_rows(runs)), use_container_width=True, hide_index=True)
