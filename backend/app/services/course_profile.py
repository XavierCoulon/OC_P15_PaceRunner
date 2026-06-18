"""Construction d'un `CourseProfile` à partir d'une liste de `TrackPoint`.

Logique partagée entre le parsing GPX (E1) et le nettoyage des altitudes (F1) :
distance (haversine), D+/D-, segmentation par kilomètre et pente moyenne.
"""

import numpy as np
from numpy.typing import NDArray

from app.domain.models import CourseProfile, ElevationSegment, TrackPoint

_SEGMENT_METERS = 1000.0
_EARTH_RADIUS_M = 6_371_000.0

FloatArray = NDArray[np.float64]


def _pairwise_distances_m(lats: FloatArray, lons: FloatArray) -> FloatArray:
    """Distances (m) entre points consécutifs (formule de haversine, vectorisée)."""
    lat1 = np.radians(lats[:-1])
    lat2 = np.radians(lats[1:])
    dlat = lat2 - lat1
    dlon = np.radians(lons[1:] - lons[:-1])
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    distances: FloatArray = 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(a))
    return distances


def build_course_profile(points: list[TrackPoint]) -> CourseProfile:
    """Agrège des points de tracé en profil de parcours.

    Lève `ValueError` si moins de deux points ou si la distance totale est nulle.
    """
    if len(points) < 2:
        raise ValueError("Au moins deux points sont nécessaires.")

    lats = np.array([p.lat for p in points], dtype=float)
    lons = np.array([p.lon for p in points], dtype=float)
    eles = np.array([p.elevation_m for p in points], dtype=float)

    pair_dist = _pairwise_distances_m(lats, lons)
    cum_dist = np.concatenate([[0.0], np.cumsum(pair_dist)])
    total_distance = float(cum_dist[-1])
    if total_distance <= 0:
        raise ValueError("Tracé de longueur nulle.")

    delta_ele = np.diff(eles)
    total_gain = float(delta_ele[delta_ele > 0].sum())
    total_loss = float(-delta_ele[delta_ele < 0].sum())

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
        points=points,
    )
