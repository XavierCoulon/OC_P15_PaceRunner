"""ActivityHistoryProvider : historique des courses COROS via `querySportRecords`.

Réutilise le client MCP maison (`CorosClient`). COROS renvoie un **texte formaté** (un bloc
par course, le plus récent d'abord) qu'on parse en `ActivitySummary`. La pagination se fait
**par fenêtres de dates** : COROS plafonne le nombre de résultats par appel, donc on remonte
le temps tant qu'une page est pleine. Dégradation gracieuse : tout échec → liste partielle.
"""

import re
from datetime import UTC, date, datetime, timedelta

from app.adapters.coros_client import CorosClient, MCPToolClient
from app.domain.models import ActivitySummary

_TOOL = "querySportRecords"
# Codes COROS « course à pied » : 100 = outdoor run, 102 = trail run.
RUN_SPORT_CODES = [100, 102]
_PAGE_LIMIT = 50
_TIMEZONE = "Europe/Paris"
# COROS time out sur les plages trop larges : on remonte le temps par fenêtres bornées.
_WINDOW = timedelta(days=365)
_BACKFILL_MAX_YEARS = 12
# Arrêt du backfill après N fenêtres consécutives sans course (assez de marge pour une coupure).
_MAX_EMPTY_WINDOWS = 3

# Découpe la réponse en blocs « N. <sport> — <date> … » (le numéro ouvre chaque enregistrement).
_RECORD_SPLIT = re.compile(r"(?=^\s*\d+\.\s)", re.MULTILINE)
_HEADER = re.compile(r"^\s*\d+\.\s+(?P<sport>.+?)\s+—\s+(?P<date>\d{4}-\d{2}-\d{2})", re.MULTILINE)
_COORDS = re.compile(r"Start Coordinates:\s*(-?\d+\.\d+),\s*(-?\d+\.\d+)")
_TIMESTAMP = re.compile(r"startTimestamp=(\d+)")
_DURATION = re.compile(r"Duration:\s*([\d:]+)")
_DISTANCE = re.compile(r"Distance:\s*([\d.]+)\s*km")
_PACE = re.compile(r"Average Pace:\s*(\d+):(\d{2})\s*/km")
_HR = re.compile(r"Avg HR:\s*(\d+)\s*bpm")
_LOCATION = re.compile(r"Location:\s*(.+)")
_LABEL = re.compile(r"LabelId:\s*(\d+)")
_SPORT_TYPE = re.compile(r"SportType:\s*(\d+)")


def _parse_duration(text: str) -> int | None:
    """« 1:00:00 » → 3600 s ; « 45:00 » → 2700 s."""
    parts = text.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return None


def parse_sport_records(text: str) -> list[ActivitySummary]:
    """Parse `querySportRecords` en `ActivitySummary` (un bloc incomplet est ignoré)."""
    summaries: list[ActivitySummary] = []
    for block in _RECORD_SPLIT.split(text):
        header = _HEADER.search(block)
        label = _LABEL.search(block)
        sport = _SPORT_TYPE.search(block)
        ts = _TIMESTAMP.search(block)
        dist = _DISTANCE.search(block)
        dur = _DURATION.search(block)
        if not (header and label and sport and ts and dist and dur):
            continue
        duration_s = _parse_duration(dur.group(1))
        if duration_s is None:
            continue
        pace = _PACE.search(block)
        hr = _HR.search(block)
        coords = _COORDS.search(block)
        location = _LOCATION.search(block)
        summaries.append(
            ActivitySummary(
                label_id=label.group(1),
                sport_type=int(sport.group(1)),
                start_timestamp=int(ts.group(1)),
                activity_date=date.fromisoformat(header.group("date")),
                distance_km=float(dist.group(1)),
                duration_s=duration_s,
                avg_pace_sec_per_km=float(int(pace.group(1)) * 60 + int(pace.group(2)))
                if pace
                else None,
                avg_hr=int(hr.group(1)) if hr else None,
                start_lat=float(coords.group(1)) if coords else None,
                start_lon=float(coords.group(2)) if coords else None,
                location=location.group(1).strip() if location else None,
            )
        )
    return summaries


class CorosActivityHistoryProvider:
    """Implémente `ActivityHistoryProvider` via `querySportRecords` (paginé)."""

    def __init__(self, client: MCPToolClient | None = None) -> None:
        self._client: MCPToolClient = client or CorosClient()

    async def list_activities(
        self, *, since: int | None = None, sport_codes: list[int] | None = None
    ) -> list[ActivitySummary]:
        """Récupère toutes les courses postérieures à `since` (epoch s).

        `since=None` → backfill complet (jusqu'à `_BACKFILL_MAX_YEARS` en arrière). On remonte le
        temps par **fenêtres bornées** (COROS time out sur les plages trop larges), en
        dédupliquant par `label_id` et en s'arrêtant après quelques fenêtres vides d'affilée.
        """
        codes = sport_codes or RUN_SPORT_CODES
        floor = (
            datetime.fromtimestamp(since, UTC).date()
            if since is not None
            else date.today() - timedelta(days=365 * _BACKFILL_MAX_YEARS)
        )
        collected: dict[str, ActivitySummary] = {}
        end_date = date.today()
        empty_windows = 0
        while end_date >= floor and empty_windows < _MAX_EMPTY_WINDOWS:
            window_start = max(floor, end_date - _WINDOW)
            page = parse_sport_records(await self._safe_call(window_start, end_date, codes))
            new = [a for a in page if a.label_id not in collected]
            for activity in new:
                collected[activity.label_id] = activity
            if not page:
                empty_windows += 1
                end_date = window_start - timedelta(days=1)
                continue
            empty_windows = 0
            # Page pleine → des courses plus anciennes restent dans la fenêtre ; sinon on saute
            # à la fenêtre précédente (toute la fenêtre courante a été lue).
            if len(page) >= _PAGE_LIMIT and new:
                oldest = min(a.start_timestamp for a in page)
                end_date = datetime.fromtimestamp(oldest, UTC).date() - timedelta(days=1)
            else:
                end_date = window_start - timedelta(days=1)
        activities = [a for a in collected.values() if since is None or a.start_timestamp > since]
        return sorted(activities, key=lambda a: a.start_timestamp)

    async def _safe_call(self, start: date, end: date, sport_codes: list[int]) -> str:
        """Appelle `querySportRecords` ; renvoie une chaîne vide en cas d'échec (dégradation)."""
        args = {
            "startDate": start.strftime("%Y%m%d"),
            "endDate": end.strftime("%Y%m%d"),
            "sportTypeCodes": sport_codes,
            "minDistanceKm": None,
            "maxDistanceKm": None,
            "minDurationMinutes": None,
            "maxDurationMinutes": None,
            "maxAveragePace": None,
            "locationKeyword": None,
            "limit": _PAGE_LIMIT,
            "timezone": _TIMEZONE,
        }
        try:
            return await self._client.call_tool(_TOOL, args)
        except Exception:
            return ""
