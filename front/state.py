"""Types d'état mémorisés dans `st.session_state` (persistance entre reruns / pages).

Définis dans un **module importé** (et non dans la page) pour que les classes soient **stables** :
Streamlit ré-exécute le script de page à chaque interaction, donc une classe définie dans la page
serait recréée à chaque run et un `isinstance(objet_mémorisé, …)` échouerait après navigation.
"""

from dataclasses import dataclass

from app.domain.models import (
    AthleteProfile,
    CourseSummary,
    PaceStrategy,
    StrategyComparison,
    WeatherContext,
)


@dataclass
class GenResult:
    """Résultat « Générer » mémorisé (profil + forme + météo + reco)."""

    profile: CourseSummary
    athlete: AthleteProfile | None
    weather: WeatherContext | None
    recommended: PaceStrategy | None


@dataclass
class CompareResult:
    """Résultat « Comparer » mémorisé."""

    comp: StrategyComparison
