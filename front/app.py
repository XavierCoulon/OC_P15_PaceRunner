"""Front Streamlit — page « Génération de stratégie ».

K1 : layout + formulaire (GPX, date/heure, objectif). L'appel au backend (`POST /strategy`)
et la restitution (graphes, tableau km/km, badge IA/fallback) viennent aux tickets K2–K5.
"""

from datetime import date, datetime, time

import streamlit as st

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
        st.session_state["request"] = {
            "filename": gpx_file.name,
            "race_datetime": race_datetime.isoformat(),
            "goal": _goal_text(),
        }
        st.success(
            f"Paramètres validés — **{gpx_file.name}**, "
            f"course le **{race_datetime:%d/%m/%Y à %H:%M}**, objectif : *{_goal_text()}*."
        )
        st.info("Prochaine étape : appel du backend `POST /strategy` (ticket K2).")
else:
    st.info("⬅️ Renseigne les paramètres dans la barre latérale, puis « Générer la stratégie ».")
