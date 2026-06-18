"""Tests du parser GPX → CourseProfile."""

import pytest

from app.adapters.gpx_parser import GpxParseError, parse_gpx


def _gpx(points: list[tuple[float, float, float]]) -> str:
    body = "".join(
        f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele></trkpt>' for lat, lon, ele in points
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{body}</trkseg></trk></gpx>"
    )


def _flat_course() -> str:
    # ~3,2 km à plat (pas de 0,001° de latitude ≈ 111 m).
    return _gpx([(45.0 + i * 0.001, 6.0, 1000.0) for i in range(30)])


def _hilly_course() -> str:
    # Montée régulière : +10 m par point.
    return _gpx([(45.0 + i * 0.001, 6.0, 1000.0 + i * 10) for i in range(30)])


def test_flat_course_distance_and_no_gain() -> None:
    profile = parse_gpx(_flat_course())
    assert 3.0 < profile.distance_km < 3.5
    assert profile.elevation_gain_m == 0.0
    assert profile.elevation_loss_m == 0.0
    assert profile.start_lat == pytest.approx(45.0)
    assert profile.start_lon == pytest.approx(6.0)
    assert all(abs(seg.gradient_pct) < 0.1 for seg in profile.segments)


def test_segments_are_per_kilometer() -> None:
    profile = parse_gpx(_flat_course())
    # ~3,2 km → 4 tronçons, indexés à partir de 1 et consécutifs.
    assert len(profile.segments) == 4
    assert [s.km_index for s in profile.segments] == [1, 2, 3, 4]


def test_hilly_course_has_positive_gain() -> None:
    profile = parse_gpx(_hilly_course())
    assert profile.elevation_gain_m == pytest.approx(290.0)
    assert profile.elevation_loss_m == 0.0
    assert all(seg.gradient_pct > 0 for seg in profile.segments)


def test_corrupt_gpx_raises() -> None:
    with pytest.raises(GpxParseError):
        parse_gpx("ceci n'est pas un fichier GPX")


def test_single_point_raises() -> None:
    with pytest.raises(GpxParseError):
        parse_gpx(_gpx([(45.0, 6.0, 1000.0)]))
