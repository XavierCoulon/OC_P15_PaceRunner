"""Ports du domaine (interfaces) sous forme de `Protocol`.

L'orchestrateur (`strategy_service`) dépend de ces abstractions, pas des adapters
concrets (Open Topo Data, COROS, Open-Meteo, Overpass, LLM HF). Cela permet
l'injection de dépendances et le remplacement par des doubles de test.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.models import (
    AthleteProfile,
    CourseProfile,
    PaceStrategy,
    RaceContext,
    SurfaceContext,
    WeatherContext,
)


@runtime_checkable
class ElevationProvider(Protocol):
    """Nettoie/corrige les altitudes d'un profil (bruit barométrique du GPX)."""

    async def clean_elevations(self, profile: CourseProfile) -> CourseProfile: ...


@runtime_checkable
class AthleteProvider(Protocol):
    """Fournit la forme de l'athlète (COROS, mono-utilisateur)."""

    async def get_athlete_profile(self) -> AthleteProfile: ...


@runtime_checkable
class WeatherProvider(Protocol):
    """Fournit les conditions prévues à un point et une date/heure donnés."""

    async def get_weather(self, lat: float, lon: float, when: datetime) -> WeatherContext: ...


@runtime_checkable
class SurfaceProvider(Protocol):
    """Fournit le type de surface du parcours."""

    async def get_surface(self, profile: CourseProfile) -> SurfaceContext: ...


@runtime_checkable
class StrategyGenerator(Protocol):
    """Produit une stratégie d'allure à partir des données consolidées."""

    async def generate(
        self,
        course: CourseProfile,
        race: RaceContext,
        athlete: AthleteProfile | None,
        weather: WeatherContext | None,
        surface: SurfaceContext | None,
        baseline: PaceStrategy | None = None,
        autonomous: bool = False,
    ) -> PaceStrategy: ...


@runtime_checkable
class PredictionRepository(Protocol):
    """Journalise un run de génération (entrée, contextes, stratégie, métriques)."""

    async def save_run(
        self,
        *,
        gpx_hash: str,
        course: CourseProfile,
        race: RaceContext,
        athlete: AthleteProfile | None,
        weather: WeatherContext | None,
        surface: SurfaceContext | None,
        strategy: PaceStrategy,
        latency_ms: float,
        guardrails_passed: bool,
        deviation_vs_baseline_pct: float,
    ) -> None: ...
