"""Page Monitoring — santé du service de production « Générer » (DeepSeek ancré, C5).

Suit les générations recommandées (POST /strategy/generate, journalisées) : volume,
part IA acceptée vs repli baseline (garde-fous), personnalisation (calibration), écart à
la baseline (ampleur de la tactique) et latence du moteur.
"""

import pandas as pd
import streamlit as st

from api_client import BackendError, fetch_history, fetch_stats

st.set_page_config(page_title="Monitoring — PaceRunner", page_icon="📊", layout="wide")

st.title("📊 Monitoring — service de production")
st.caption(
    "Stratégies recommandées générées (bouton « Générer », DeepSeek ancré). "
    "Part IA vs repli baseline, personnalisation, écart à la baseline, latence."
)

try:
    stats = fetch_stats()
    runs = fetch_history(limit=100)
except BackendError as exc:
    st.error(str(exc))
    st.stop()

if stats.total_runs == 0:
    st.info(
        "Aucune génération journalisée pour l'instant. Lance une stratégie via « Générer » "
        "(les comparaisons « Comparer » ne sont pas comptées ici)."
    )
    st.stop()

cols = st.columns(5)
cols[0].metric("Générations", stats.total_runs)
cols[1].metric("Part IA (vs repli)", f"{stats.llm_share_pct:.0f} %")
cols[2].metric("Personnalisées", f"{stats.calibration_used_pct:.0f} %")
cols[3].metric(
    "Écart moy. vs baseline",
    f"{stats.avg_deviation_vs_baseline_pct:+.1f} %"
    if stats.avg_deviation_vs_baseline_pct is not None
    else "—",
)
cols[4].metric(
    "Latence moy.",
    f"{stats.avg_latency_ms / 1000:.1f} s" if stats.avg_latency_ms is not None else "—",
)
st.caption(
    f"« Part IA » = stratégies où la sortie DeepSeek a passé les garde-fous "
    f"({stats.llm_runs}/{stats.total_runs}) ; sinon repli baseline déterministe."
)

if not runs:
    st.stop()

df = pd.DataFrame(
    [
        {
            "id": run.id,
            "origine": "IA (DeepSeek)" if run.generated_by == "llm" else "Repli baseline",
            "latence_s": round((run.latency_ms or 0) / 1000, 1),
            "ecart_pct": run.deviation_vs_baseline_pct or 0.0,
        }
        for run in runs
    ]
)

left, right = st.columns(2)
with left:
    st.subheader("Origine des stratégies")
    st.bar_chart(df["origine"].value_counts())
with right:
    st.subheader("Latence par génération (s)")
    st.line_chart(df.set_index("id")["latence_s"])
