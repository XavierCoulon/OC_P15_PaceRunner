"""Front Streamlit — page « Génération de stratégie ».

K1 : layout + formulaire. K2 : appel backend. K3 : profil de dénivelé + courbe d'allure.
Le tableau km/km (K4) et le bandeau météo (réponse à enrichir) viennent ensuite.
"""

from datetime import date, datetime
from datetime import time as dtime

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from api_client import (
    BackendError,
    fetch_athlete,
    fetch_profile,
    fetch_weather,
    generate_strategy,
)
from app.config import get_settings
from app.domain.models import AthleteProfile, PaceStrategy, RoutePoint, WeatherContext
from viz import km_table_rows, strategy_rows, weather_summary

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


def _render_map(route: list[RoutePoint]) -> None:
    if not route:
        return
    st.subheader("Tracé du parcours")
    coords = pd.DataFrame([{"lat": p.lat, "lon": p.lon} for p in route])
    token = get_settings().mapbox_token
    if token is None:
        st.map(coords, zoom=11)
        st.caption("Ajoute `MAPBOX_TOKEN` dans `.env` pour un fond relief/satellite.")
        return

    mid = route[len(route) // 2]
    layer = pdk.Layer(
        "PathLayer",
        data=[{"path": [[p.lon, p.lat] for p in route]}],
        get_path="path",
        get_color=[230, 80, 40],
        width_min_pixels=3,
    )
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=mid.lat, longitude=mid.lon, zoom=12),
        map_provider="mapbox",
        map_style="mapbox://styles/mapbox/outdoors-v12",
        api_keys={"mapbox": token.get_secret_value()},
    )
    st.pydeck_chart(deck)


def _render_athlete(athlete: AthleteProfile | None) -> None:
    if athlete is None:
        return
    st.subheader("🏃 Forme du jour (COROS)")
    cols = st.columns(4)
    cols[0].metric(
        "Allure seuil",
        _fmt_pace(athlete.threshold_pace_sec_per_km)
        if athlete.threshold_pace_sec_per_km is not None
        else "—",
    )
    cols[1].metric("VO2max", f"{athlete.vo2max:.0f}" if athlete.vo2max is not None else "—")
    cols[2].metric(
        "Récupération",
        f"{athlete.recovery_pct:.0f} %" if athlete.recovery_pct is not None else "—",
    )
    cols[3].metric("Poids", f"{athlete.weight_kg:.1f} kg" if athlete.weight_kg is not None else "—")
    if athlete.recovery_status:
        st.caption(f"État : {athlete.recovery_status}")


def _render_weather(weather: WeatherContext | None) -> None:
    if weather is None or weather.source is None:
        st.info("☁️ Conditions jour J indisponibles (hors horizon de prévision).")
        return
    source = _WEATHER_SOURCE_LABEL.get(weather.source, weather.source)
    emoji, label = weather_summary(weather.weather_code)
    temp = f"{weather.temperature_c:.0f} °C" if weather.temperature_c is not None else "—"
    st.subheader(f"{emoji} Conditions jour J — {label}, {temp}")
    st.caption(f"Source : {source}")
    cols = st.columns(4)
    cols[0].metric("🌡️ Température", temp)
    cols[1].metric(
        "💨 Vent",
        f"{weather.wind_speed_kmh:.0f} km/h" if weather.wind_speed_kmh is not None else "—",
    )
    cols[2].metric(
        "🌧️ Précip.",
        f"{weather.precipitation_mm:.1f} mm" if weather.precipitation_mm is not None else "—",
    )
    cols[3].metric(
        "🟢 Qualité air",
        f"{weather.air_quality_index:.0f}" if weather.air_quality_index is not None else "—",
    )
    if weather.last_year_temperature_c is not None:
        st.caption(f"📅 Même date l'an dernier : {weather.last_year_temperature_c:.0f} °C")


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
        race_time = col_time.time_input("Heure de départ", value=dtime(9, 0))

        submitted = st.form_submit_button("Générer la stratégie", type="primary")


if submitted:
    if gpx_file is None:
        st.warning("Merci de fournir un fichier GPX.")
    elif isinstance(race_date, date) and isinstance(race_time, dtime):
        gpx_bytes = gpx_file.getvalue()
        filename = gpx_file.name
        race_iso = datetime.combine(race_date, race_time).isoformat()

        # 1) Profil + carte (rapide) — affiché dès que prêt.
        try:
            with st.spinner("📍 Analyse du parcours…"):
                profile = fetch_profile(gpx_bytes=gpx_bytes, filename=filename)
        except BackendError as exc:
            st.error(str(exc))
            st.stop()

        cols = st.columns(2)
        cols[0].metric("Distance", f"{profile.distance_km:.2f} km")
        cols[1].metric("Dénivelé +", f"{profile.elevation_gain_m:.0f} m")
        _render_map(profile.route)

        # 2) Forme COROS.
        with st.spinner("🏃 Récupération de la forme COROS…"):
            try:
                athlete = fetch_athlete()
            except BackendError:
                athlete = None
        _render_athlete(athlete)

        # 3) Météo jour J.
        with st.spinner("🌤️ Récupération de la météo jour J…"):
            try:
                weather = fetch_weather(
                    lat=profile.start_lat, lon=profile.start_lon, race_datetime_iso=race_iso
                )
            except BackendError:
                weather = None
        _render_weather(weather)

        # 4) Stratégie (génération LLM — le plus long).
        try:
            with st.spinner("🧠 Génération de la stratégie (IA)…"):
                response = generate_strategy(
                    gpx_bytes=gpx_bytes,
                    filename=filename,
                    race_datetime_iso=race_iso,
                )
        except BackendError as exc:
            st.error(str(exc))
            st.stop()

        strategy = response.strategy
        st.session_state["strategy"] = response.model_dump()
        badge = "🤖 Stratégie IA" if strategy.generated_by == "llm" else "🛡️ Repli déterministe"
        st.success(f"Stratégie générée — **{badge}**")
        if strategy.generated_by != "llm":
            st.warning("Le modèle n'a pas produit de stratégie valide : repli sur la baseline.")

        cols = st.columns(2)
        cols[0].metric("Temps estimé", _fmt_duration(strategy.estimated_time_sec))
        cols[1].metric("Allure moyenne", _fmt_pace(strategy.average_pace_sec_per_km))
        if strategy.summary:
            st.caption(strategy.summary)

        _render_charts(strategy)
        _render_km_table(strategy)
else:
    st.info("⬅️ Renseigne les paramètres dans la barre latérale, puis « Générer la stratégie ».")
