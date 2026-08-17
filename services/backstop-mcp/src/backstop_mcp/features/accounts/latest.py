"""Latest point on a dated Backstop series.

Do not `sort=-date&page[limit]=1` and take the first row. Backstop drops query params it does
not implement — no 400, same payload — so a 200 with `sort=-date` is not proof the series was
reordered. Party opportunities already showed this: `sort=modifiedTimestamp` and
`sort=-modifiedTimestamp` came back byte-identical. Default order on `/accounts/{id}/values` is
oldest first (the current end of a long series sits on a late `page[offset]`, not item 0). If
sort is ignored and we take the first row, the oldest historical point is returned as "current".

`filter[date][ge]` is the documented alternative, and it actually filters. A 90-day window of
monthly or daily points fits in one `page[limit]=100`. `max(date)` over that complete window is
the latest point without trusting sort, and is not "last of month" — a mid-month estimate still
wins. Each window is walked to the end so a first page of older points cannot hide a later date.

If the quarter is empty, widen once to a year; if that is empty too, paginate the unfiltered
series. Walking the whole history first would also be correct, just expensive (three series per
open account).
"""

from collections.abc import Sequence
from datetime import date, timedelta

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.accounts.types import SeriesPoint, SeriesPointAttributes

_LOOKBACK_DAYS = 90
_WIDENED_LOOKBACK_DAYS = 365
_PAGE_SIZE = 100
_DATE_FILTER = "filter[date][ge]"

# Plain assignment — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
SeriesPointResource = BackstopApiResource[SeriesPointAttributes]


def latest_point(resources: Sequence[SeriesPointResource]) -> SeriesPoint | None:
    """The point with the greatest `date`, or `None` when nothing dated is on the page."""
    points = tuple(point for resource in resources if (point := _dated_point(resource)) is not None)
    if not points:
        return None
    return max(points, key=lambda point: point.date)


async def fetch_latest_point(
    client: BackstopClient,
    path: str,
    *,
    today: date,
) -> SeriesPoint | None:
    """Latest point on `path`, widening the date window only when the narrower one is empty."""
    for days in (_LOOKBACK_DAYS, _WIDENED_LOOKBACK_DAYS):
        point = await _latest_in_window(client, path, cutoff=today - timedelta(days=days))
        if point is not None:
            return point
    return await _latest_in_window(client, path, cutoff=None)


def _dated_point(resource: SeriesPointResource) -> SeriesPoint | None:
    point_date = resource.attributes.date
    if point_date is None:
        return None
    return SeriesPoint.model_validate({**resource.attributes.model_dump(), "date": point_date})


async def _latest_in_window(
    client: BackstopClient,
    path: str,
    *,
    cutoff: date | None,
) -> SeriesPoint | None:
    params: dict[str, object] = {} if cutoff is None else {_DATE_FILTER: cutoff.isoformat()}
    page = await client.paginate(
        path,
        schema=SeriesPointResource,
        params=params,
        max_records=None,
        page_size=_PAGE_SIZE,
    )
    return latest_point(page.items)
