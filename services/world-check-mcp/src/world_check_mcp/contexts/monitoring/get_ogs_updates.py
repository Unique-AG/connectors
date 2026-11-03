from datetime import datetime
from datetime import timedelta
from datetime import UTC
import json

from world_check_mcp.contexts.cases import get_case
from world_check_mcp.contexts.monitoring.errors import MonitoringError
from world_check_mcp.contexts.monitoring.models import OgsPage
from world_check_mcp.contexts.monitoring.models import OgsUpdate
from world_check_mcp.contexts.monitoring.models import OgsWindow
from world_check_mcp.contexts.monitoring.models import UpdateMode
from world_check_mcp.upstream import GET_ONGOING_SCREENING_UPDATES
from world_check_mcp.upstream import GetOngoingScreeningUpdatesRequest
from world_check_mcp.upstream import next_page
from world_check_mcp.upstream import OgsUpdateFilterInput
from world_check_mcp.upstream import PaginationReferenceRequestInput
from world_check_mcp.upstream import SortCriterionInput
from world_check_mcp.upstream import Upstream
from world_check_mcp.upstream import UpstreamError
from world_check_mcp.upstream import WatchlistResults

_EMPTY = "NO_OGS_CASE_UPDATES_FOUND_WITHIN_DATE_RANGE"


async def get_ogs_updates(
    *,
    upstream: Upstream,
    since: datetime | None = None,
    until: datetime | None = None,
    group_id: str | None = None,
    case: str | None = None,
    limit: int = 100,
    page_reference: str | None = None,
    mode: UpdateMode = "FULL",
) -> OgsPage:
    """WATCHLIST monitoring updates. Defaults to the last 24 hours inside a 30-day window."""
    if page_reference is not None and (since is None or until is None):
        raise MonitoringError("Reuse both since and until from the first page.")
    start, end = _window(since=since, until=until)
    resolved = None if case is None else await get_case(upstream=upstream, case=case)
    case_system_id = None if resolved is None else resolved.case_system_id
    try:
        found = await upstream.call(
            GET_ONGOING_SCREENING_UPDATES,
            GetOngoingScreeningUpdatesRequest(
                body=OgsUpdateFilterInput(
                    filter=_filter(
                        start=start, end=end, group_id=group_id, case_system_id=case_system_id
                    ),
                    sort=[SortCriterionInput(column_name="updateDate", order="ASCENDING")],
                    pagination=PaginationReferenceRequestInput(
                        items_per_page=limit, page_reference=page_reference
                    ),
                    mode=mode,
                )
            ),
        )
    except UpstreamError as error:
        if error.status_code != 404 or _EMPTY not in str(error):
            raise
        return OgsPage(window=OgsWindow(since=start, until=end), updates=[], next_page=None)
    return OgsPage(
        window=OgsWindow(since=start, until=end),
        updates=[
            OgsUpdate(
                case_id=item.case_id,
                case_system_id=item.case_system_id,
                group_id=item.group_id,
                update_date=item.update_date,
                new_results=_count(counts=item.watchlist_results, updated=False),
                updated_results=_count(counts=item.watchlist_results, updated=True),
            )
            for item in found.results
        ],
        next_page=next_page(found.pagination),
    )


def _window(*, since: datetime | None, until: datetime | None) -> tuple[str, str]:
    now = datetime.now(UTC)
    end = until or now
    start = since or end - timedelta(days=1)
    if start.tzinfo is None or end.tzinfo is None:
        raise MonitoringError("Use timezone-aware timestamps.")
    if not now - timedelta(days=30) <= start < end <= now:
        raise MonitoringError("Use an increasing range inside the last 30 days, not in the future.")
    return _stamp(value=start), _stamp(value=end)


def _filter(*, start: str, end: str, group_id: str | None, case_system_id: str | None) -> str:
    parts = [f"updateDate=RANGE=({start},{end})", "providerType==WATCHLIST"]
    if group_id is not None:
        parts.append(f"groupId=={json.dumps(group_id, ensure_ascii=False)}")
    if case_system_id is not None:
        parts.append(f"caseSystemId=={json.dumps(case_system_id, ensure_ascii=False)}")
    return ";".join(parts)


def _count(*, counts: WatchlistResults | None, updated: bool) -> int | None:
    if counts is None:
        return None
    return counts.number_of_updated_results if updated else counts.number_of_new_results


def _stamp(*, value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
