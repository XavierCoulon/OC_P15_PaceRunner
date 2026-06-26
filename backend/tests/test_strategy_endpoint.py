"""Tests de l'endpoint POST /strategy (pipeline complet, providers stubés)."""

from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.adapters.coros_mock import CorosMockAthleteProvider
from app.adapters.prediction_repo import NullPredictionRepository
from app.api.routes import (
    get_athlete_provider,
    get_calibration_store,
    get_deepseek_generator,
    get_elevation_provider,
    get_llama_generator,
    get_prediction_repository,
    get_weather_provider,
)
from app.config import get_settings
from app.db.calibration import NullCalibrationStore
from app.domain.models import (
    AthleteProfile,
    CalibrationProfile,
    CourseProfile,
    KmPlan,
    PaceStrategy,
    RaceContext,
    SurfaceContext,
    WeatherContext,
)
from app.main import app

_TOKEN = "secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _gpx() -> str:
    points = "".join(
        f'<trkpt lat="{43.0 + i * 0.001}" lon="6.0"><ele>{1000.0 + i * 5}</ele></trkpt>'
        for i in range(20)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{points}</trkseg></trk></gpx>"
    )


class _FakeElevation:
    async def clean_elevations(self, profile: CourseProfile) -> CourseProfile:
        return profile


class _FakeWeather:
    async def get_weather(self, lat: float, lon: float, when: datetime) -> WeatherContext:
        return WeatherContext()


class _FailingGenerator:
    async def generate(self, *args: object, **kwargs: object) -> PaceStrategy:
        raise RuntimeError("LLM indisponible")  # force le fallback baseline


class _ValidGenerator:
    """Renvoie une stratégie alignée sur le parcours (un km_plan par segment)."""

    async def generate(
        self,
        course: CourseProfile,
        race: RaceContext,
        athlete: AthleteProfile | None,
        weather: WeatherContext | None,
        surface: SurfaceContext | None,
        baseline: PaceStrategy | None = None,
        mode: str = "anchored",
        calibration: CalibrationProfile | None = None,
    ) -> PaceStrategy:
        plans = [
            KmPlan(
                km_index=s.km_index,
                target_pace_sec_per_km=330.0,
                effort="steady",
                gradient_pct=s.gradient_pct,
            )
            for s in course.segments
        ]
        return PaceStrategy(
            distance_km=course.distance_km,
            estimated_time_sec=1.0,
            average_pace_sec_per_km=1.0,
            km_plans=plans,
            summary=f"variante {mode}",
            generated_by="llm",
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("API_TOKEN", _TOKEN)
    get_settings.cache_clear()
    app.dependency_overrides[get_elevation_provider] = _FakeElevation
    app.dependency_overrides[get_athlete_provider] = CorosMockAthleteProvider
    app.dependency_overrides[get_weather_provider] = _FakeWeather
    app.dependency_overrides[get_llama_generator] = _FailingGenerator
    app.dependency_overrides[get_deepseek_generator] = _FailingGenerator
    app.dependency_overrides[get_calibration_store] = NullCalibrationStore
    app.dependency_overrides[get_prediction_repository] = NullPredictionRepository
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_generate_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/strategy/generate",
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 401


def test_generate_rejects_invalid_gpx(client: TestClient) -> None:
    response = client.post(
        "/strategy/generate",
        headers=_AUTH,
        files={"gpx": ("bad.gpx", "pas du gpx", "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 422


def test_health_remains_public(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_profile_returns_course(client: TestClient) -> None:
    response = client.post(
        "/profile",
        headers=_AUTH,
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["distance_km"] > 0
    assert len(body["route"]) >= 1
    assert "strategy" not in body  # aperçu, pas la stratégie


def test_profile_requires_auth(client: TestClient) -> None:
    response = client.post("/profile", files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")})
    assert response.status_code == 401


def test_profile_rejects_invalid_gpx(client: TestClient) -> None:
    response = client.post(
        "/profile",
        headers=_AUTH,
        files={"gpx": ("bad.gpx", "pas du gpx", "application/gpx+xml")},
    )
    assert response.status_code == 422


def test_compare_returns_baseline_and_two_variants(client: TestClient) -> None:
    app.dependency_overrides[get_llama_generator] = _ValidGenerator
    app.dependency_overrides[get_deepseek_generator] = _ValidGenerator
    response = client.post(
        "/strategy/compare",
        headers=_AUTH,
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["baseline"]["generated_by"] == "baseline"
    # « Comparer » : pas de reco ancrée, seulement le comparatif.
    assert body["recommended"] is None
    # 2 variantes : llama3.1:8b autonome, DeepSeek CoT.
    variants = body["variants"]
    assert [v["mode"] for v in variants] == ["autonomous", "cot"]
    for v in variants:
        assert v["error"] is None
        assert v["strategy"]["generated_by"] == f"llm_{v['mode']}"


class _RecordingRepository:
    def __init__(self) -> None:
        self.runs: list[dict[str, object]] = []

    async def save_run(self, **kwargs: object) -> None:
        self.runs.append(kwargs)


def test_generate_journals_one_run(client: TestClient) -> None:
    repo = _RecordingRepository()
    app.dependency_overrides[get_deepseek_generator] = _ValidGenerator
    app.dependency_overrides[get_prediction_repository] = lambda: repo
    response = client.post(
        "/strategy/generate",
        headers=_AUTH,
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 200
    # La reco de production est journalisée (monitoring) ; la calibration est absente (NullStore).
    assert len(repo.runs) == 1
    assert repo.runs[0]["calibration_used"] is False


def test_compare_does_not_journal(client: TestClient) -> None:
    repo = _RecordingRepository()
    app.dependency_overrides[get_llama_generator] = _ValidGenerator
    app.dependency_overrides[get_deepseek_generator] = _ValidGenerator
    app.dependency_overrides[get_prediction_repository] = lambda: repo
    response = client.post(
        "/strategy/compare",
        headers=_AUTH,
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 200
    assert repo.runs == []  # « Comparer » = benchmark, non journalisé


def test_generate_returns_only_recommended(client: TestClient) -> None:
    app.dependency_overrides[get_deepseek_generator] = _ValidGenerator
    response = client.post(
        "/strategy/generate",
        headers=_AUTH,
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 200
    body = response.json()
    # « Générer » = un seul appel : la reco ancrée, sans variante de comparaison.
    assert body["recommended"]["generated_by"] in ("llm", "baseline")
    assert len(body["recommended"]["km_plans"]) == len(body["course"]["segments"])
    assert body["variants"] == []


def test_compare_reports_variant_failure(client: TestClient) -> None:
    # Générateurs en échec (fixture) → chaque variante porte une erreur, baseline présente.
    response = client.post(
        "/strategy/compare",
        headers=_AUTH,
        files={"gpx": ("course.gpx", _gpx(), "application/gpx+xml")},
        data={"race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["baseline"]["generated_by"] == "baseline"
    for v in body["variants"]:
        assert v["strategy"] is None and v["error"] is not None


def test_weather_returns_context(client: TestClient) -> None:
    response = client.get(
        "/weather",
        headers=_AUTH,
        params={"lat": 43.0, "lon": 6.0, "race_datetime": "2026-09-01T09:00:00"},
    )
    assert response.status_code == 200
    assert "source" in response.json()


def test_weather_requires_auth(client: TestClient) -> None:
    response = client.get(
        "/weather", params={"lat": 43.0, "lon": 6.0, "race_datetime": "2026-09-01T09:00:00"}
    )
    assert response.status_code == 401


def test_sample_route_limits_and_keeps_endpoints() -> None:
    from app.api.routes import sample_route
    from app.domain.models import TrackPoint

    points = [TrackPoint(lat=43.0 + i * 0.0001, lon=6.0, elevation_m=10.0) for i in range(1000)]
    route = sample_route(points)
    assert len(route) <= 301
    assert route[0].lat == points[0].lat
    assert route[-1].lat == points[-1].lat
    assert sample_route([]) == []
