"""Feature-local grouping models for one activity-history stream page."""

from datetime import date
from typing import Annotated, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backstop_mcp.features.activity_history.fetch_activities import ActivityType

__all__ = ["ActivityContinuation", "ActivityGroup", "DateRange"]


def _require_since_not_after_until(since: date | None, until: date | None) -> None:
    if since is not None and until is not None and since > until:
        raise ValueError("since must not be after until")


class DateRange(BaseModel):
    """Min/max `occurred_at` among this page's dated items."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    start: Annotated[
        date,
        Field(description="Oldest `occurred_at` date among this page's dated items."),
    ]
    end: Annotated[
        date,
        Field(description="Newest `occurred_at` date among this page's dated items."),
    ]

    @model_validator(mode="after")
    def _start_not_after_end(self) -> Self:
        if self.start > self.end:
            raise ValueError("date_range.start must not be after date_range.end")
        return self


class ActivityContinuation(BaseModel):
    """Params to fetch this stream's next page. Echo from a prior group's `next`; do not invent."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    limit: Annotated[
        int,
        Field(gt=0, description="Page size for this stream. Copy from the prior group's `next`."),
    ]
    offset: Annotated[
        int,
        Field(
            ge=0,
            description=(
                "Next `page[offset]` for this stream. Copy from the prior group's `next`."
            ),
        ),
    ]
    since: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Lower date bound for this stream, copied from the prior group's `next`. "
                "Omitted (or null) when this stream has no lower bound — do not invent one."
            ),
        ),
    ] = None
    until: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Upper date bound for this stream, copied from the prior group's `next`. "
                "Omitted (or null) when this stream has no upper bound — do not invent one."
            ),
        ),
    ] = None

    @model_validator(mode="after")
    def _since_not_after_until(self) -> Self:
        _require_since_not_after_until(self.since, self.until)
        return self


class ActivityGroup[ItemT](BaseModel):
    """One stream's page: which type, this page's items, this page's date span, and continuation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    activity_type: Annotated[
        ActivityType,
        Field(description="Which stream this group is: meeting, call, note, email, or document."),
    ]
    items: Annotated[
        tuple[ItemT, ...],
        Field(description="This page's records for `activity_type`, in Backstop fetch order."),
    ]
    date_range: Annotated[
        DateRange | None,
        Field(
            description=(
                "Oldest and newest `occurred_at` dates among this page's dated items. Omitted "
                "(or null) when the page is empty or every item lacks a date."
            ),
        ),
    ] = None
    next: Annotated[
        ActivityContinuation | None,
        Field(
            description=(
                "Params to fetch this stream's next page. Omitted (or null) once the stream is "
                "exhausted. To continue, copy this object into a `type=next` request's `next` "
                "map under this `activity_type`."
            ),
        ),
    ] = None
