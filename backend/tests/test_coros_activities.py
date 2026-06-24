"""Tests de l'historique COROS : parsing `querySportRecords`, pagination, dégradation."""

from datetime import date, datetime
from typing import Any

from app.adapters.coros_activities import CorosActivityHistoryProvider, parse_sport_records

_BLOCK_RUN = """1. Outdoor Run — 2026-06-21
   Location: Bayonne Course
   Start Coordinates: 43.474998, -1.484000
   Time Window: startTimestamp=1782026694 | endTimestamp=1782030295
   Duration: 1:00:00 | Distance: 9.14 km
   Average Pace: 6:34 /km | Avg HR: 131 bpm | Calories: 566 kcal
   LabelId: 478360125394944303 | SportType: 100
"""

_BLOCK_TRAIL = """2. Trail Run — 2026-06-12
   Location: Birac-sur-Trec Course
   Start Coordinates: 44.473000, 0.230000
   Time Window: startTimestamp=1781251269 | endTimestamp=1781257320
   Duration: 1:40:11 | Distance: 16.26 km
   Average Pace: 6:10 /km | Avg HR: 139 bpm | Calories: 1044 kcal
   LabelId: 478152632035213415 | SportType: 102
"""

_HEADER_LINE = "Sport Records — sample (2 records)\n========================\n\n"
_SAMPLE = _HEADER_LINE + _BLOCK_RUN + "\n" + _BLOCK_TRAIL


class _WindowClient:
    """Simule COROS : ne renvoie que les courses dont la date tombe dans [startDate, endDate]."""

    def __init__(self) -> None:
        self.calls = 0
        self._records = [(date(2026, 6, 21), _BLOCK_RUN), (date(2026, 6, 12), _BLOCK_TRAIL)]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls += 1
        start = datetime.strptime(arguments["startDate"], "%Y%m%d").date()
        end = datetime.strptime(arguments["endDate"], "%Y%m%d").date()
        kept = [block for day, block in self._records if start <= day <= end]
        return _HEADER_LINE + "\n".join(kept)


class _FailClient:
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        raise RuntimeError("COROS KO")


def test_parse_extracts_fields() -> None:
    activities = parse_sport_records(_SAMPLE)
    assert len(activities) == 2
    run = activities[0]
    assert run.label_id == "478360125394944303"
    assert run.sport_type == 100
    assert run.start_timestamp == 1782026694
    assert run.activity_date.isoformat() == "2026-06-21"
    assert run.distance_km == 9.14
    assert run.duration_s == 3600
    assert run.avg_pace_sec_per_km == 394.0  # 6:34
    assert run.avg_hr == 131
    assert run.start_lat == 43.474998
    assert run.location == "Bayonne Course"
    # Durée H:MM:SS du second enregistrement.
    assert activities[1].duration_s == 6011  # 1:40:11


def test_parse_skips_incomplete_block() -> None:
    broken = _SAMPLE.replace("LabelId: 478360125394944303 | SportType: 100", "SportType: 100")
    activities = parse_sport_records(broken)
    assert {a.label_id for a in activities} == {"478152632035213415"}


async def test_list_activities_sorted_ascending_and_stops_on_empty() -> None:
    client = _WindowClient()
    provider = CorosActivityHistoryProvider(client=client)
    activities = await provider.list_activities()
    assert [a.start_timestamp for a in activities] == [1781251269, 1782026694]
    # 1 fenêtre avec données + 3 fenêtres vides consécutives → arrêt.
    assert client.calls == 4


async def test_list_activities_since_filters() -> None:
    provider = CorosActivityHistoryProvider(client=_WindowClient())
    activities = await provider.list_activities(since=1781251269)
    assert [a.label_id for a in activities] == ["478360125394944303"]


async def test_list_activities_graceful_on_failure() -> None:
    provider = CorosActivityHistoryProvider(client=_FailClient())
    assert await provider.list_activities() == []
