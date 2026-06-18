"""Parsing d'un fichier GPX → `CourseProfile` (gpxpy + numpy).

Calcule distance totale, dénivelés (D+/D-), point de départ et une segmentation par
kilomètre (pente moyenne). Les altitudes brutes du GPX sont bruitées (baromètre) :
leur nettoyage fin est délégué à l'`ElevationProvider` (Open Topo Data, ticket F1).
"""

import gpxpy
import gpxpy.geo
import numpy as np

from app.domain.models import CourseProfile, ElevationSegment

_SEGMENT_METERS = 1000.0


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

    points = [
        point for track in gpx.tracks for segment in track.segments for point in segment.points
    ]
    if len(points) < 2:
        raise GpxParseError("Le GPX doit contenir au moins deux points de tracé.")

    lats = np.array([p.latitude for p in points], dtype=float)
    lons = np.array([p.longitude for p in points], dtype=float)
    eles = np.array([p.elevation if p.elevation is not None else 0.0 for p in points], dtype=float)

    # Distance (m) entre points consécutifs, puis distance cumulée.
    pair_dist = np.array(
        [
            gpxpy.geo.haversine_distance(lats[i], lons[i], lats[i + 1], lons[i + 1])
            for i in range(len(points) - 1)
        ],
        dtype=float,
    )
    cum_dist = np.concatenate([[0.0], np.cumsum(pair_dist)])
    total_distance = float(cum_dist[-1])
    if total_distance <= 0:
        raise GpxParseError("Tracé GPX de longueur nulle.")

    delta_ele = np.diff(eles)
    total_gain = float(delta_ele[delta_ele > 0].sum())
    total_loss = float(-delta_ele[delta_ele < 0].sum())

    # Affectation de chaque paire à un kilomètre (selon la distance cumulée de départ).
    buckets = (cum_dist[:-1] // _SEGMENT_METERS).astype(int)

    segments: list[ElevationSegment] = []
    for bucket in np.unique(buckets):
        mask = buckets == bucket
        dist_m = float(pair_dist[mask].sum())
        if dist_m <= 0:
            continue
        deltas = delta_ele[mask]
        indices = np.nonzero(mask)[0]
        start_ele = float(eles[indices[0]])
        end_ele = float(eles[indices[-1] + 1])
        gradient = (end_ele - start_ele) / dist_m * 100
        segments.append(
            ElevationSegment(
                km_index=int(bucket) + 1,
                distance_km=round(dist_m / 1000, 3),
                elevation_gain_m=round(float(deltas[deltas > 0].sum()), 1),
                elevation_loss_m=round(float(-deltas[deltas < 0].sum()), 1),
                gradient_pct=round(gradient, 2),
            )
        )

    return CourseProfile(
        distance_km=round(total_distance / 1000, 3),
        elevation_gain_m=round(total_gain, 1),
        elevation_loss_m=round(total_loss, 1),
        start_lat=float(lats[0]),
        start_lon=float(lons[0]),
        segments=segments,
    )
