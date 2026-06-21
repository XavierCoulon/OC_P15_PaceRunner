"""Front Streamlit — page « Génération de stratégie ».

K1 : layout + formulaire. K2 : appel backend. K3 : profil de dénivelé + courbe d'allure.
Le tableau km/km (K4) et le bandeau météo (réponse à enrichir) viennent ensuite.
"""

from datetime import date, datetime, time

import altair as alt
import pandas as pd
import streamlit as st

from api_client import BackendError, generate_strategy
from app.domain.models import PaceStrategy, WeatherContext
from viz import km_table_rows, strategy_rows

_WEATHER_SOURCE_LABEL = {
    "forecast": "Prévision",
    "seasonal": "Tendance saisonnière",
    "climatology": "Climatologie (normales)",
}


def _fmt_duration(seconds: float) -> str:
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _fmt_pace(seconds_per_km: float) -> str:
    minutes, secs = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{secs:02d} /km"


def _render_weather(weather: WeatherContext | None) -> None:
    if weather is None or weather.source is None:
        st.info("Conditions jour J indisponibles (hors horizon de prévision).")
        return
    label = _WEATHER_SOURCE_LABEL.get(weather.source, weather.source)
    st.subheader(f"Conditions jour J — {label}")
    cols = st.columns(4)
    cols[0].metric(
        "Température",
        f"{weather.temperature_c:.0f} °C" if weather.temperature_c is not None else "—",
    )
    cols[1].metric(
        "Vent", f"{weather.wind_speed_kmh:.0f} km/h" if weather.wind_speed_kmh is not None else "—"
    )
    cols[2].metric(
        "Précip.",
        f"{weather.precipitation_mm:.1f} mm" if weather.precipitation_mm is not None else "—",
    )
    cols[3].metric(
        "Qualité air",
        f"{weather.air_quality_index:.0f}" if weather.air_quality_index is not None else "—",
    )
    if weather.last_year_temperature_c is not None:
        st.caption(f"Même date l'an dernier : {weather.last_year_temperature_c:.0f} °C")


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
    # Ligne continue (neutre) + points colorés par effort : colorer la ligne elle-même
    # la découperait en segments séparés par couleur (trous aux changements d'effort).
    pace_base = alt.Chart(df).encode(
        x=alt.X("km:Q", title="Kilomètre"),
        # axe inversé : une allure plus rapide (moins de secondes) est plus haute
        y=alt.Y("pace_sec:Q", title="Allure (s/km)", scale=alt.Scale(reverse=True)),
    )
    pace_line = pace_base.mark_line(color="#9aa0a6")
    pace_points = pace_base.mark_point(filled=True, size=70, opacity=1).encode(
        color=alt.Color("effort:N", title="Effort"),
        tooltip=["km", alt.Tooltip("pace_label", title="allure"), "effort", "gradient_pct"],
    )
    st.altair_chart(pace_line + pace_points, use_container_width=True)


def _render_km_table(strategy: PaceStrategy) -> None:
    st.subheader("Stratégie kilomètre par kilomètre")
    table = pd.DataFrame(km_table_rows(strategy))
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Exporter en CSV",
        data=table.to_csv(index=False).encode("utf-8"),
        file_name="strategie_pacerunner.csv",
        mime="text/csv",
    )


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
                response = generate_strategy(
                    gpx_bytes=gpx_file.getvalue(),
                    filename=gpx_file.name,
                    race_datetime_iso=race_datetime.isoformat(),
                    goal=_goal_text(),
                )
            except BackendError as exc:
                response = None
                st.error(str(exc))

        if response is not None:
            strategy = response.strategy
            st.session_state["strategy"] = response.model_dump()
            badge = "🤖 Stratégie IA" if strategy.generated_by == "llm" else "🛡️ Repli déterministe"
            st.success(f"Stratégie générée — **{badge}**")
            if strategy.generated_by != "llm":
                st.warning("Le modèle n'a pas produit de stratégie valide : repli sur la baseline.")

            cols = st.columns(4)
            cols[0].metric("Distance", f"{response.course.distance_km:.2f} km")
            cols[1].metric("Dénivelé +", f"{response.course.elevation_gain_m:.0f} m")
            cols[2].metric("Temps estimé", _fmt_duration(strategy.estimated_time_sec))
            cols[3].metric("Allure moyenne", _fmt_pace(strategy.average_pace_sec_per_km))
            if response.athlete and response.athlete.threshold_pace_sec_per_km:
                st.caption(
                    f"Allure seuil COROS : {_fmt_pace(response.athlete.threshold_pace_sec_per_km)}"
                )
            if strategy.summary:
                st.caption(strategy.summary)

            _render_weather(response.weather)
            _render_charts(strategy)
            _render_km_table(strategy)
else:
    st.info("⬅️ Renseigne les paramètres dans la barre latérale, puis « Générer la stratégie ».")
