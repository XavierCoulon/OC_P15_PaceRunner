"""Page Monitoring — KPIs du modèle (`GET /stats`) + graphes (C5)."""

import pandas as pd
import streamlit as st

from api_client import BackendError, fetch_history, fetch_stats

st.set_page_config(page_title="Monitoring — PaceRunner", page_icon="📊", layout="wide")

st.title("📊 Monitoring du modèle")
st.caption("Suivi de la génération : volume, part IA, garde-fous, écart à la baseline, latence.")

try:
    stats = fetch_stats()
    runs = fetch_history(limit=100)
except BackendError as exc:
    st.error(str(exc))
    st.stop()

cols = st.columns(5)
cols[0].metric("Runs", stats.total_runs)
cols[1].metric("Part IA", f"{stats.llm_share_pct:.0f} %")
cols[2].metric("Garde-fous OK", f"{stats.guardrails_passed_pct:.0f} %")
cols[3].metric(
    "Écart moy. baseline",
    f"{stats.avg_deviation_vs_baseline_pct:+.1f} %"
    if stats.avg_deviation_vs_baseline_pct is not None
    else "—",
)
cols[4].metric(
    "Latence moy.",
    f"{stats.avg_latency_ms / 1000:.1f} s" if stats.avg_latency_ms is not None else "—",
)

if not runs:
    st.info("Aucune donnée à représenter pour l'instant.")
    st.stop()

df = pd.DataFrame(
    [
        {
            "id": run.id,
            "origine": "IA" if run.generated_by == "llm" else "Repli",
            "latence_s": round((run.latency_ms or 0) / 1000, 1),
            "ecart_pct": run.deviation_vs_baseline_pct or 0.0,
        }
        for run in runs
    ]
)

left, right = st.columns(2)
with left:
    st.subheader("Répartition IA vs repli")
    st.bar_chart(df["origine"].value_counts())
with right:
    st.subheader("Latence par run (s)")
    st.line_chart(df.set_index("id")["latence_s"])
