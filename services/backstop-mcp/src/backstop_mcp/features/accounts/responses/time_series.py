"""`get_time_series` response: one entity, one series, the dated points."""

from datetime import date as Date
from typing import Literal, Self

from pydantic import Field

from backstop_mcp.features.accounts.internal_dto import SeriesPointDto
from backstop_mcp.features.accounts.time_series_name import TimeSeriesEntityType, TimeSeriesName
from backstop_mcp.models import OmitNoneModel


class TimeSeriesPointResponse(OmitNoneModel):
    """One dated point. A missing `value` is "not in yet", not zero."""

    date: Date = Field(description="The day this point is as-of.")
    value: float | None = Field(
        default=None,
        description=(
            "The point's amount. `0.0` is a real published zero. Absent means Backstop has "
            "the date but no number yet (its UI shows `-`) — do not report that as zero, and "
            "do not treat an unused fee series of zeroes as 'this account has no NAV'."
        ),
    )
    value_status: str | None = Field(
        default=None,
        description=(
            "Account extra: Backstop's `valueStatus` when present (`ESTIMATE` / `ACTUAL`). "
            "Omitted when Backstop did not send one — not defaulted to `ACTUAL`. Product "
            "series never carry this."
        ),
    )
    source: str | None = Field(
        default=None,
        description=(
            "Product-`aums` extra: where the AUM figure came from (e.g. 'AUM from Accounts'). "
            "Omitted on every other series."
        ),
    )

    @classmethod
    def from_point(cls, point: SeriesPointDto) -> Self:
        return cls(
            date=point.date,
            value=point.value,
            value_status=point.value_status,
            source=point.source,
        )


class TimeSeriesResolvedResponse(OmitNoneModel):
    """The dated points of one series on one account or product, newest first."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the series was fetched.",
    )
    entity_type: TimeSeriesEntityType = Field(
        description="Which collection `entity_id` belongs to: `accounts` or `products`."
    )
    entity_id: str = Field(
        description=(
            "The account or product id these points belong to. Echo it on a later call — "
            "never invent one."
        )
    )
    series: TimeSeriesName = Field(description="Which time series these points are.")
    points: tuple[TimeSeriesPointResponse, ...] = Field(
        description=(
            "Dated points, newest first. An empty list means this series has no points in "
            "the window, not that the entity does not exist."
        )
    )

    @classmethod
    def from_points(
        cls,
        *,
        entity_type: TimeSeriesEntityType,
        entity_id: str,
        series: TimeSeriesName,
        points: tuple[SeriesPointDto, ...],
    ) -> Self:
        return cls(
            entity_type=entity_type,
            entity_id=entity_id,
            series=series,
            points=tuple(TimeSeriesPointResponse.from_point(point) for point in points),
        )
