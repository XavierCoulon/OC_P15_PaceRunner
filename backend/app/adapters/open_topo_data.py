"""ElevationProvider : nettoyage des altitudes via Open Topo Data (API publique).

Récupère l'altitude « terrain » (modèle numérique) pour chaque point du tracé afin de
corriger le bruit barométrique du GPX, puis reconstruit le profil. En cas d'indisponibilité
de l'API, renvoie le profil d'origine inchangé (dégradation gracieuse).
"""

import httpx

from app.config import Settings, get_settings
from app.domain.models import CourseProfile, TrackPoint
from app.services.course_profile import build_course_profile

_MAX_LOCATIONS_PER_REQUEST = 100


class OpenTopoDataProvider:
    """Implémente le port `ElevationProvider`."""

    def __init__(self, settings: Settings | None = None) -> None:
        config = settings or get_settings()
        self._base_url = config.open_topo_data_url
        self._dataset = config.open_topo_data_dataset
        self._timeout = config.http_timeout_seconds

    async def clean_elevations(self, profile: CourseProfile) -> CourseProfile:
        if len(profile.points) < 2:
            return profile
        try:
            elevations = await self._fetch_elevations(profile.points)
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return profile  # dégradation : on garde les altitudes GPX
        if len(elevations) != len(profile.points) or any(e is None for e in elevations):
            return profile
        cleaned = [
            TrackPoint(
                lat=p.lat,
                lon=p.lon,
                elevation_m=float(e) if e is not None else p.elevation_m,
            )
            for p, e in zip(profile.points, elevations, strict=True)
        ]
        # On reconstruit sur les altitudes terrain, mais on conserve le D+/D- brut
        # d'origine (GPX) comme référence de comparaison côté front.
        return build_course_profile(
            cleaned,
            elevation_source="open_topo_data",
            raw_gain=profile.raw_elevation_gain_m,
            raw_loss=profile.raw_elevation_loss_m,
        )

    async def _fetch_elevations(self, points: list[TrackPoint]) -> list[float | None]:
        elevations: list[float | None] = []
        url = f"{self._base_url}/{self._dataset}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for start in range(0, len(points), _MAX_LOCATIONS_PER_REQUEST):
                chunk = points[start : start + _MAX_LOCATIONS_PER_REQUEST]
                locations = "|".join(f"{p.lat},{p.lon}" for p in chunk)
                response = await client.get(url, params={"locations": locations})
                response.raise_for_status()
                data = response.json()
                if data.get("status") != "OK":
                    raise httpx.HTTPError("Statut Open Topo Data non OK.")
                elevations.extend(result["elevation"] for result in data["results"])
        return elevations
