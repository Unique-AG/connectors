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
open account). Each window is a superset of the narrower one, so widening never loses the latest
point it already found.

`max(date)` alone is not enough either: Backstop publishes a dated row before the number lands
(the UI shows `-`), and taking that row as the figure reports a live position as "no data". So a
window is only *satisfying* once it holds a point with a value, and both points are returned —
the latest, and the latest that carries a number.
"""

from collections.abc import Sequence
from datetime import date, timedelta

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.accounts.types import (
    SeriesFigure,
    SeriesPoint,
    SeriesPointAttributes,
)

_LOOKBACK_DAYS = 90
_WIDENED_LOOKBACK_DAYS = 365
_PAGE_SIZE = 100
_DATE_FILTER = "filter[date][ge]"

# Plain assignment — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
SeriesPointResource = BackstopApiResource[SeriesPointAttributes]


def latest_figure(resources: Sequence[SeriesPointResource]) -> SeriesFigure | None:
    """The greatest-`date` point and the greatest-`date` point with a value, or `None`.

    `valued` is the same object as `latest` whenever the newest row carries a number, and `None`
    when no row on the page does.
    """
    points = tuple(point for resource in resources if (point := _dated_point(resource)) is not None)
    if not points:
        return None
    latest = max(points, key=_by_date)
    if latest.value is not None:
        return SeriesFigure(latest=latest, valued=latest)
    valued = tuple(point for point in points if point.value is not None)
    return SeriesFigure(latest=latest, valued=max(valued, key=_by_date) if valued else None)


async def fetch_latest_figure(
    client: BackstopClient,
    path: str,
    *,
    today: date,
) -> SeriesFigure | None:
    """Latest figure on `path`, widening while the window holds no point with a value.

    An empty window and a window of dated-but-valueless rows both widen: the last real number
    may simply be older than the cutoff. The widest window walked wins — it is a superset of
    the narrower ones, so its `latest` is the same point.
    """
    figure: SeriesFigure | None = None
    cutoffs = (
        today - timedelta(days=_LOOKBACK_DAYS),
        today - timedelta(days=_WIDENED_LOOKBACK_DAYS),
        None,
    )
    for cutoff in cutoffs:
        figure = await _latest_in_window(client, path, cutoff=cutoff)
        if figure is not None and figure.valued is not None:
            return figure
    return figure


def _by_date(point: SeriesPoint) -> date:
    return point.date


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
) -> SeriesFigure | None:
    params: dict[str, object] = {} if cutoff is None else {_DATE_FILTER: cutoff.isoformat()}
    page = await client.paginate(
        path,
        schema=SeriesPointResource,
        params=params,
        max_records=None,
        page_size=_PAGE_SIZE,
    )
    return latest_figure(page.items)
