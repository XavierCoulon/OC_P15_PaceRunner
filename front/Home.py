"""Front Streamlit — page « Génération de stratégie ».

Le bouton « Générer » affiche d'abord le contexte du parcours (distance, D+, carte, profil de
dénivelé), puis lance la **comparaison** : baseline déterministe + variantes LLM (moteur × prompt
autonome/CoT), avec la forme COROS et la météo jour J (cf. #74).
"""

from datetime import date, datetime
from datetime import time as dtime

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from api_client import (
    BackendError,
    compare_strategies,
    fetch_calibration_status,
    fetch_profile,
    generate_plan,
)
from app.config import get_settings
from app.domain.models import (
    AthleteProfile,
    CourseSummary,
    PaceStrategy,
    RoutePoint,
    StrategyComparison,
    WeatherContext,
)
from viz import weather_summary

_WEATHER_SOURCE_LABEL = {
    "forecast": "Prévision",
    "last_year": "Relevés de l'an dernier",
}


def _fmt_duration(seconds: float) -> str:
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _fmt_pace(seconds_per_km: float) -> str:
    minutes, secs = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{secs:02d} /km"


def _render_elevation_note(course: CourseSummary) -> None:
    """Indique l'ajustement du dénivelé (D+ brut → retenu) et la source d'altitude."""
    terrain = course.elevation_source == "open_topo_data"
    src = "altitudes terrain" if terrain else "altitudes GPX, service terrain indisponible"
    raw, final = course.raw_elevation_gain_m, course.elevation_gain_m
    if abs(raw - final) >= 1:
        st.caption(f"🗻 D+ ajusté {raw:.0f} → {final:.0f} m ({src}, bruit filtré).")
    elif terrain:
        st.caption("🗻 Altitudes terrain (Open Topo Data).")
    else:
        st.caption("ℹ️ Altitudes GPX brutes (service terrain indisponible).")


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


def _render_elevation_profile(course: CourseSummary) -> None:
    """Profil de dénivelé cumulé du parcours (niveau parcours, indépendant des stratégies)."""
    if not course.segments:
        return
    rows = []
    elev = 0.0
    for s in course.segments:
        elev += s.elevation_gain_m - s.elevation_loss_m
        rows.append(
            {"km": s.km_index, "elevation_m": round(elev, 1), "gradient_pct": s.gradient_pct}
        )
    st.subheader("Profil de dénivelé")
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_area(opacity=0.4, color="#6c8ebf", line={"color": "#3b5b8c"})
        .encode(
            x=alt.X("km:Q", title="Kilomètre"),
            y=alt.Y("elevation_m:Q", title="Dénivelé cumulé (m)"),
            tooltip=["km", "elevation_m", alt.Tooltip("gradient_pct", title="pente %")],
        )
    )
    st.altair_chart(chart, use_container_width=True)


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
        _render_weather_history(weather)
        st.info("☁️ Conditions jour J indisponibles.")
        return

    if weather.source == "last_year":
        st.subheader("⏳ Conditions jour J — pas encore disponibles")
        st.warning(
            "La course est trop lointaine pour une prévision. Voici les **relevés de "
            "l'an dernier** à cette date (indicatif)."
        )
    else:
        emoji, label = weather_summary(weather.weather_code)
        temp = f"{weather.temperature_c:.0f} °C" if weather.temperature_c is not None else "—"
        st.subheader(f"{emoji} Conditions jour J — {label}, {temp}")

    cols = st.columns(4)
    cols[0].metric(
        "🌡️ Température",
        f"{weather.temperature_c:.0f} °C" if weather.temperature_c is not None else "—",
    )
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
    _render_weather_history(weather)


def _render_weather_history(weather: WeatherContext | None) -> None:
    if weather is None or not weather.history:
        return
    rows = [
        {
            "Année": y.year,
            "Température": f"{y.temperature_c:.0f} °C" if y.temperature_c is not None else "—",
            "Vent": f"{y.wind_speed_kmh:.0f} km/h" if y.wind_speed_kmh is not None else "—",
            "Précip.": f"{y.precipitation_mm:.1f} mm" if y.precipitation_mm is not None else "—",
        }
        for y in weather.history
    ]
    st.caption("📅 Mêmes date et lieu, années précédentes :")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_recommended(strat: PaceStrategy) -> None:
    """Stratégie de production : baseline calibrée + tactique LLM bornée + narratif par tranche."""
    st.subheader("🎯 Stratégie recommandée")
    cols = st.columns(2)
    cols[0].metric("Temps estimé", _fmt_duration(strat.estimated_time_sec))
    cols[1].metric("Allure moyenne", _fmt_pace(strat.average_pace_sec_per_km))
    origin = (
        "Baseline calibrée + tactique IA"
        if strat.generated_by == "llm"
        else "Baseline déterministe (repli garde-fou)"
    )
    st.caption(f"Origine : {origin}.")
    if strat.summary:
        st.caption(strat.summary)
    if strat.section_narrative:
        st.markdown("**Plan de course par tranche :**")
        for s in strat.section_narrative:
            label = f"km {s.start_km}" if s.start_km == s.end_km else f"km {s.start_km}–{s.end_km}"
            st.markdown(f"- **{label}** — {s.note}")


def _render_comparison(comp: StrategyComparison) -> None:
    st.subheader("⚖️ Comparaison : baseline vs modèles × prompts")

    # (titre, stratégie | None, erreur | None) — baseline = référence déterministe.
    entries: list[tuple[str, PaceStrategy | None, str | None]] = [
        ("🛡️ Baseline déterministe", comp.baseline, None),
    ]
    for v in comp.variants:
        icon = "🧠" if v.mode == "cot" else "💻"
        entries.append((f"{icon} {v.label}", v.strategy, v.error))

    cols = st.columns(len(entries))
    for col, (title, strat, err) in zip(cols, entries, strict=True):
        col.markdown(f"**{title}**")
        if strat is None:
            col.error(f"Échec : {err}")
        else:
            col.metric("Temps estimé", _fmt_duration(strat.estimated_time_sec))
            col.metric("Allure moyenne", _fmt_pace(strat.average_pace_sec_per_km))

    st.caption(
        "⚠️ Variantes en mode **brut** (aucun garde-fou, aucun repli). "
        "« autonome » = one-shot ; « CoT » = raisonnement pente imposé."
    )

    # Courbes d'allure superposées (forme longue → gère des longueurs différentes).
    rows = [
        {"km": p.km_index, "Allure (s/km)": p.target_pace_sec_per_km, "Stratégie": title}
        for title, strat, _ in entries
        if strat is not None
        for p in strat.km_plans
    ]
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_line(point=True)
        .encode(
            x=alt.X("km:Q", title="Kilomètre"),
            y=alt.Y("Allure (s/km):Q", scale=alt.Scale(reverse=True)),
            color=alt.Color("Stratégie:N", title="Stratégie"),
            tooltip=["km", "Stratégie", "Allure (s/km)"],
        )
    )
    st.altair_chart(chart, use_container_width=True)

    # Tableau km/km côte à côte (uniquement les stratégies alignées sur le parcours).
    n = len(comp.baseline.km_plans)
    table: dict[str, list[object]] = {
        "km": [p.km_index for p in comp.baseline.km_plans],
        "pente %": [p.gradient_pct for p in comp.baseline.km_plans],
    }
    for title, strat, _ in entries:
        if strat is not None and len(strat.km_plans) == n:
            table[title] = [_fmt_pace(p.target_pace_sec_per_km) for p in strat.km_plans]
        elif strat is not None:
            st.caption(
                f"« {title} » : {len(strat.km_plans)} km ≠ {n} segments → exclue du tableau."
            )
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

    for title, strat, _ in entries:
        if strat is not None and strat.summary:
            st.caption(f"**{title}** — {strat.summary}")


st.set_page_config(page_title="PaceRunner", page_icon="🏃", layout="wide")

st.title("🏃 PaceRunner")
st.caption(
    "Stratégie d'allure km par km à partir d'un GPX, de ta forme COROS et de la météo jour J."
)

# Prérequis : des données COROS doivent avoir été récupérées (bloc 1). Sinon, génération bloquée.
data_ready = False
try:
    data_ready = fetch_calibration_status().activity_count > 0
except BackendError as exc:
    st.error(str(exc))

if not data_ready:
    st.warning(
        "⛔ Aucune donnée COROS en base. Va d'abord sur la page **📥 Données COROS** "
        "(barre latérale) pour récupérer ton historique — c'est le prérequis à la génération."
    )

with st.sidebar:
    st.header("Paramètres de course")
    with st.form("strategy_form"):
        gpx_file = st.file_uploader("Fichier GPX du parcours", type=["gpx"])

        col_date, col_time = st.columns(2)
        race_date = col_date.date_input(
            "Date de la course",
            value=date.today(),
            min_value=date.today(),
            format="DD/MM/YYYY",
        )
        race_time = col_time.time_input("Heure de départ", value=dtime(9, 0))

        generate_clicked = st.form_submit_button(
            "Générer la stratégie", type="primary", disabled=not data_ready
        )
        compare_clicked = st.form_submit_button("Comparer les moteurs", disabled=not data_ready)
        st.caption(
            "**Générer** : ta stratégie (baseline calibrée + DeepSeek : tranches + commentaires). "
            "**Comparer** : baseline vs llama3.1:8b autonome vs DeepSeek CoT (courbe + tableau)."
        )


if generate_clicked or compare_clicked:
    if gpx_file is None:
        st.warning("Merci de fournir un fichier GPX.")
    elif isinstance(race_date, date) and isinstance(race_time, dtime):
        gpx_bytes = gpx_file.getvalue()
        filename = gpx_file.name
        race_iso = datetime.combine(race_date, race_time).isoformat()

        if compare_clicked:
            # « Comparer » : uniquement le comparatif (courbe + tableau).
            try:
                with st.spinner("⚖️ Comparaison baseline vs llama3.1:8b vs DeepSeek…"):
                    comp = compare_strategies(
                        gpx_bytes=gpx_bytes, filename=filename, race_datetime_iso=race_iso
                    )
            except BackendError as exc:
                st.error(str(exc))
                st.stop()
            _render_comparison(comp)
        else:
            # « Générer » : profil + reco DeepSeek (tranches) + comparaison baseline/DeepSeek CoT.
            try:
                with st.spinner("📍 Analyse du parcours…"):
                    profile = fetch_profile(gpx_bytes=gpx_bytes, filename=filename)
            except BackendError as exc:
                st.error(str(exc))
                st.stop()

            cols = st.columns(2)
            cols[0].metric("Distance", f"{profile.distance_km:.2f} km")
            cols[1].metric("Dénivelé +", f"{profile.elevation_gain_m:.0f} m")
            _render_elevation_note(profile)
            _render_map(profile.route)
            _render_elevation_profile(profile)

            try:
                with st.spinner("🎯 Stratégie recommandée (DeepSeek)…"):
                    comp = generate_plan(
                        gpx_bytes=gpx_bytes, filename=filename, race_datetime_iso=race_iso
                    )
            except BackendError as exc:
                st.error(str(exc))
                st.stop()

            _render_athlete(comp.athlete)
            _render_weather(comp.weather)
            if comp.recommended is not None:
                _render_recommended(comp.recommended)
else:
    st.info("⬅️ Renseigne les paramètres dans la barre latérale, puis « Générer » ou « Comparer ».")
