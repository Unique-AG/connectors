"""Latest point on a dated Backstop series.

`GET /accounts/{id}/values` (and the sibling series, and `/products/{id}/aums`) default to
oldest first. `sort=-date` is implemented on those paths — confirmed by comparing `sort=date`
and `sort=-date`, which are not byte-identical the way party-opportunity `sort=` is.

Do not reintroduce a `today` cutoff. Fetch the first 10 rows of `sort=-date` and pick
`max(date)` on that page. A mid-month estimate still wins. `max(date)` alone is not enough:
Backstop publishes a dated row before the number lands (the UI shows `-`), so both points are
returned — the latest, and the latest that carries a number. Ten newest rows is enough for
that pair without walking history.
"""

from collections.abc import Sequence
from datetime import date

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.accounts.api_responses import SeriesPointAttributes
from backstop_mcp.features.accounts.internal_dto import SeriesFigureDto, SeriesPointDto

# Plain assignment — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
SeriesPointResource = BackstopApiResource[SeriesPointAttributes]


def _latest_figure(resources: Sequence[SeriesPointResource]) -> SeriesFigureDto | None:
    """The greatest-`date` point and the greatest-`date` point with a value, or `None`.

    `valued` is the same object as `latest` whenever the newest row carries a number, and `None`
    when no row on the page does.
    """
    points = tuple(point for resource in resources if (point := _dated_point(resource)) is not None)
    if not points:
        return None
    latest = max(points, key=_by_date)
    if latest.value is not None:
        return SeriesFigureDto(latest=latest, valued=latest)
    valued = tuple(point for point in points if point.value is not None)
    return SeriesFigureDto(latest=latest, valued=max(valued, key=_by_date) if valued else None)


async def fetch_series(client: BackstopClient, path: str) -> SeriesFigureDto | None:
    """Latest figure on `path`: first 10 rows of `sort=-date`, then `_latest_figure`."""
    page = await client.fetch_page(
        path,
        schema=SeriesPointResource,
        params={"sort": "-date"},
        page_size=10,
    )
    return _latest_figure(page.items)


def _by_date(point: SeriesPointDto) -> date:
    return point.date


def _dated_point(resource: SeriesPointResource) -> SeriesPointDto | None:
    return SeriesPointDto.from_attributes(resource.attributes)
