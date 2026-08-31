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
    SeriesPointDto,
    TimeSeriesEntityType,
    TimeSeriesName,
)
from backstop_mcp.features.accounts.responses import TimeSeriesResolvedResponse

# Plain assignment — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
SeriesPointResource = BackstopApiResource[SeriesPointAttributes]


class GetTimeSeriesQuery:
    """Every dated point on one series, newest first. Undated rows are dropped, not zeroed."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        entity_type: TimeSeriesEntityType,
        entity_id: str,
        series: TimeSeriesName,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TimeSeriesResolvedResponse:
        path = f"/{entity_type}/{quote(entity_id, safe='')}/{series}"
        page = await self._client.paginate(
            path,
            schema=SeriesPointResource,
            params=self._params(
                entity_type=entity_type,
                series=series,
                start_date=start_date,
                end_date=end_date,
            ),
            max_records=None,
        )
        return TimeSeriesResolvedResponse.from_points(
            entity_type=entity_type,
            entity_id=entity_id,
            series=series,
            points=tuple(
                point
                for resource in page.items
                if (point := SeriesPointDto.from_attributes(resource.attributes)) is not None
            ),
        )

    def _params(
        self,
        *,
        entity_type: TimeSeriesEntityType,
        series: TimeSeriesName,
        start_date: date | None,
        end_date: date | None,
    ) -> dict[str, object]:
        params: dict[str, object] = {
            "sort": "-date",
            "fields": self._fields(entity_type, series),
        }
        if start_date is not None:
            params["filter[date][ge]"] = start_date.isoformat()
        if end_date is not None:
            params["filter[date][le]"] = end_date.isoformat()
        return params

    def _fields(self, entity_type: TimeSeriesEntityType, series: TimeSeriesName) -> str:
        if entity_type == "accounts":
            return "date,value,valueStatus"
        if series == "aums":
            return "date,value,source"
        return "date,value"
