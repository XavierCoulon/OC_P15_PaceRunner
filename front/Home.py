"""Front Streamlit — page « Génération de stratégie ».

K1 : layout + formulaire. K2 : appel backend. K3 : profil de dénivelé + courbe d'allure.
Le tableau km/km (K4) et le bandeau météo (réponse à enrichir) viennent ensuite.
"""

from datetime import date, datetime, time

import altair as alt
import pandas as pd
import streamlit as st

from api_client import BackendError, generate_strategy
from app.domain.models import PaceStrategy
from viz import strategy_rows


def _fmt_duration(seconds: float) -> str:
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _fmt_pace(seconds_per_km: float) -> str:
    minutes, secs = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{secs:02d} /km"


def _render_charts(strategy: PaceStrategy) -> None:
    df = pd.DataFrame(strategy_rows(strategy))

    st.subheader("Profil de dénivelé")
    elevation = (
        alt.Chart(df)
        .mark_area(opacity=0.4, color="#6c8ebf", line={"color": "#3b5b8c"})
        .encode(
            x=alt.X("km:Q", title="Kilomètre"),
            y=alt.Y("elevation_m:Q", title="Dénivelé cumulé (m)"),
            tooltip=["km", "elevation_m", alt.Tooltip("gradient_pct", title="pente %")],
        )
    )
    st.altair_chart(elevation, use_container_width=True)

    st.subheader("Allure conseillée par km")
    pace = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("km:Q", title="Kilomètre"),
            # axe inversé : une allure plus rapide (moins de secondes) est plus haute
            y=alt.Y("pace_sec:Q", title="Allure (s/km)", scale=alt.Scale(reverse=True)),
            color=alt.Color("effort:N", title="Effort"),
            tooltip=["km", alt.Tooltip("pace_label", title="allure"), "effort", "gradient_pct"],
        )
    )
    st.altair_chart(pace, use_container_width=True)


st.set_page_config(page_title="PaceRunner", page_icon="🏃", layout="wide")

st.title("🏃 PaceRunner")
st.caption(
    "Stratégie d'allure km par km à partir d'un GPX, de ta forme COROS et de la météo jour J."
)

with st.sidebar:
    st.header("Paramètres de course")
    with st.form("strategy_form"):
        gpx_file = st.file_uploader("Fichier GPX du parcours", type=["gpx"])

        col_date, col_time = st.columns(2)
        race_date = col_date.date_input("Date de la course", value=date.today())
        race_time = col_time.time_input("Heure de départ", value=time(9, 0))

        goal_mode = st.selectbox(
            "Objectif",
            options=["Laisser l'IA décider", "Allure cible", "Temps visé"],
        )
        goal_detail = ""
        if goal_mode == "Allure cible":
            goal_detail = st.text_input("Allure cible (min/km)", placeholder="ex. 4:50")
        elif goal_mode == "Temps visé":
            goal_detail = st.text_input("Temps visé (h:min:s)", placeholder="ex. 1:45:00")

        submitted = st.form_submit_button("Générer la stratégie", type="primary")


def _goal_text() -> str:
    if goal_mode == "Laisser l'IA décider" or not goal_detail:
        return "Laisser l'IA décider"
    return f"{goal_mode} : {goal_detail}"


if submitted:
    if gpx_file is None:
        st.warning("Merci de fournir un fichier GPX.")
    elif isinstance(race_date, date) and isinstance(race_time, time):
        race_datetime = datetime.combine(race_date, race_time)
        with st.spinner("Génération de la stratégie… (le modèle peut prendre quelques secondes)"):
            try:
                strategy = generate_strategy(
                    gpx_bytes=gpx_file.getvalue(),
                    filename=gpx_file.name,
                    race_datetime_iso=race_datetime.isoformat(),
                    goal=_goal_text(),
                )
            except BackendError as exc:
                strategy = None
                st.error(str(exc))

        if strategy is not None:
            st.session_state["strategy"] = strategy.model_dump()
            badge = "🤖 Stratégie IA" if strategy.generated_by == "llm" else "🛡️ Repli déterministe"
            st.success(f"Stratégie générée — **{badge}**")
            if strategy.generated_by != "llm":
                st.warning("Le modèle n'a pas produit de stratégie valide : repli sur la baseline.")

            cols = st.columns(3)
            cols[0].metric("Distance", f"{strategy.distance_km:.2f} km")
            cols[1].metric("Temps estimé", _fmt_duration(strategy.estimated_time_sec))
            cols[2].metric("Allure moyenne", _fmt_pace(strategy.average_pace_sec_per_km))
            if strategy.summary:
                st.caption(strategy.summary)

            _render_charts(strategy)
            st.caption("Tableau km/km (K4) et bandeau météo jour J (réponse à enrichir) à venir.")
else:
    st.info("⬅️ Renseigne les paramètres dans la barre latérale, puis « Générer la stratégie ».")
