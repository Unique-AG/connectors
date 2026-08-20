"""Paginate one Backstop time series for one account or one product.

`GET /{accounts|products}/{id}/{timeSeries}` is the only documented source of a dated,
status-labelled figure. One series per call — there is no bulk path (`GET /time-series` is
`400 Find all time-series is not allowed.`). Optional `filter[date][ge]` / `[le]` narrow the
window; with no dates the whole series is walked. `sort=-date` is newest first.

Sparse fieldsets match the extras Backstop actually sends: `valueStatus` on accounts,
`source` on product `aums`. Other product series are `date,value` only.
"""

from datetime import date
from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.accounts.api_responses import SeriesPointAttributes
from backstop_mcp.features.accounts.internal_dto import (
    ACCOUNT_SERIES,
    PRODUCT_SERIES,
    SeriesPointDto,
    TimeSeriesEntityType,
    TimeSeriesName,
)

_SORT = "sort"
_ACCOUNT_FIELDS = "date,value,valueStatus"
_AUMS_FIELDS = "date,value,source"
_PRODUCT_FIELDS = "date,value"

# Plain assignment — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
SeriesPointResource = BackstopApiResource[SeriesPointAttributes]


def _time_series_params(
    *,
    entity_type: TimeSeriesEntityType,
    series: TimeSeriesName,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, object]:
    """Query params for one series GET, including the sparse fieldset that entity uses."""
    params: dict[str, object] = {
        _SORT: "-date",
        "fields": _fields(entity_type, series),
    }
    if start_date is not None:
        params["filter[date][ge]"] = start_date.isoformat()
    if end_date is not None:
        params["filter[date][le]"] = end_date.isoformat()
    return params


def _allowed_series(entity_type: TimeSeriesEntityType) -> frozenset[str]:
    return ACCOUNT_SERIES if entity_type == "accounts" else PRODUCT_SERIES


def _fields(entity_type: TimeSeriesEntityType, series: TimeSeriesName) -> str:
    if entity_type == "accounts":
        return _ACCOUNT_FIELDS
    if series == "aums":
        return _AUMS_FIELDS
    return _PRODUCT_FIELDS


def require_series_for_entity(entity_type: TimeSeriesEntityType, series: TimeSeriesName) -> None:
    """Raise when `series` is not on this entity type's swagger enum.

    The tool parameter type is the union of both enums, so pairing is this check rather than
    pydantic's. An unrecognized path segment is silently a 404 on some Backstop versions.
    """
    allowed = _allowed_series(entity_type)
    if series in allowed:
        return
    names = ", ".join(sorted(allowed))
    raise ValueError(f"series {series!r} is not valid for {entity_type}: {names}")


async def fetch_time_series(
    client: BackstopClient,
    *,
    entity_type: TimeSeriesEntityType,
    entity_id: str,
    series: TimeSeriesName,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[SeriesPointDto, ...]:
    """Every dated point on this series, newest first. Undated rows are dropped, not zeroed."""
    assert series in _allowed_series(entity_type), (
        f"series {series!r} is not valid for {entity_type}"
    )
    path = f"/{entity_type}/{quote(entity_id, safe='')}/{series}"
    page = await client.paginate(
        path,
        schema=SeriesPointResource,
        params=_time_series_params(
            entity_type=entity_type,
            series=series,
            start_date=start_date,
            end_date=end_date,
        ),
        max_records=None,
    )
    return tuple(
        point
        for resource in page.items
        if (point := SeriesPointDto.from_attributes(resource.attributes)) is not None
    )
