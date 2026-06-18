"""Parsing d'un fichier GPX → `CourseProfile` (gpxpy).

Extrait les points de tracé puis délègue l'agrégation (distance, D+/D-, segments) à
`build_course_profile`. Les altitudes brutes du GPX sont bruitées (baromètre) : leur
nettoyage fin est délégué à l'`ElevationProvider` (Open Topo Data, ticket F1).
"""

import gpxpy

from app.domain.models import CourseProfile, TrackPoint
from app.services.course_profile import build_course_profile


class GpxParseError(ValueError):
    """Le contenu GPX est invalide ou inexploitable (vide, corrompu…)."""


def parse_gpx(content: str) -> CourseProfile:
    """Transforme le contenu d'un fichier GPX en `CourseProfile`.

    Lève `GpxParseError` si le GPX est illisible ou contient moins de deux points.
    """
    try:
        gpx = gpxpy.parse(content)
    except Exception as exc:  # gpxpy lève divers types selon la nature du défaut
        raise GpxParseError("Fichier GPX illisible.") from exc

    raw = [point for track in gpx.tracks for segment in track.segments for point in segment.points]
    if len(raw) < 2:
        raise GpxParseError("Le GPX doit contenir au moins deux points de tracé.")

    points = [
        TrackPoint(
            lat=p.latitude,
            lon=p.longitude,
            elevation_m=float(p.elevation) if p.elevation is not None else 0.0,
        )
        for p in raw
    ]
    try:
        return build_course_profile(points)
    except ValueError as exc:
        raise GpxParseError(str(exc)) from exc
