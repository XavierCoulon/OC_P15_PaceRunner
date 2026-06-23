"""Tests de l'adapter Open Topo Data (mocké) + dégradation gracieuse."""

import httpx
import respx

from app.adapters.open_topo_data import OpenTopoDataProvider
from app.domain.models import CourseProfile, TrackPoint
from app.services.course_profile import build_course_profile

_API = "https://api.opentopodata.org/v1/aster30m"


def _profile() -> CourseProfile:
    points = [TrackPoint(lat=45.0 + i * 0.001, lon=6.0, elevation_m=1000.0) for i in range(5)]
    return build_course_profile(points)


@respx.mock
async def test_clean_replaces_elevations_and_recomputes_gain() -> None:
    profile = _profile()
    payload = {
        "status": "OK",
        "results": [{"elevation": 1000.0 + i * 20} for i in range(5)],
    }
    respx.get(url__startswith=_API).mock(return_value=httpx.Response(200, json=payload))

    cleaned = await OpenTopoDataProvider().clean_elevations(profile)

    assert cleaned.elevation_gain_m == 80.0  # 4 montées de 20 m
    assert cleaned.points[-1].elevation_m == 1080.0
    # Source marquée terrain ; le D+ brut d'origine (plat → 0) est préservé.
    assert cleaned.elevation_source == "open_topo_data"
    assert cleaned.raw_elevation_gain_m == 0.0


@respx.mock
async def test_clean_preserves_raw_gain_reference() -> None:
    # Tracé bruité (±2 m sous le seuil) : D+ brut > 0, terrain régulier → D+ retenu nul.
    eles = [1000.0 + (2.0 if i % 2 else -2.0) for i in range(6)]
    noisy = build_course_profile(
        [TrackPoint(lat=45.0 + i * 0.001, lon=6.0, elevation_m=e) for i, e in enumerate(eles)]
    )
    assert noisy.raw_elevation_gain_m > 0  # le brut capture le bruit
    payload = {"status": "OK", "results": [{"elevation": 1000.0} for _ in range(6)]}
    respx.get(url__startswith=_API).mock(return_value=httpx.Response(200, json=payload))

    cleaned = await OpenTopoDataProvider().clean_elevations(noisy)

    assert cleaned.elevation_gain_m == 0.0  # terrain plat retenu
    assert cleaned.raw_elevation_gain_m == noisy.raw_elevation_gain_m  # brut GPX conservé


@respx.mock
async def test_degrades_on_http_error() -> None:
    profile = _profile()
    respx.get(url__startswith=_API).mock(return_value=httpx.Response(500))

    cleaned = await OpenTopoDataProvider().clean_elevations(profile)

    assert cleaned == profile  # profil inchangé


@respx.mock
async def test_degrades_on_non_ok_status() -> None:
    profile = _profile()
    respx.get(url__startswith=_API).mock(
        return_value=httpx.Response(200, json={"status": "INVALID_REQUEST", "results": []})
    )

    cleaned = await OpenTopoDataProvider().clean_elevations(profile)

    assert cleaned == profile
