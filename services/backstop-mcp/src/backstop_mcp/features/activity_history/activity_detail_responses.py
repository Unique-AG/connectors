"""Wire response model for `get_activity_detail`, and the pure conversion into it.

A separate module from `responses.py` because it's a different tool's output entirely (one
activity's full detail, not a timeline page) — same fetch-layer/response-layer split as
`fetch_activities.py` / `responses.py`, mirrored here as `fetch_activity_detail.py` /
`activity_detail_responses.py`.

Pass-through fields are mapped with `from_attributes` / `model_validate` (same pattern as
`data_hygiene/responses.py`). Only the HTML→Markdown body conversion and the attendees join
are spelled out explicitly.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import ConfigDict, Field

from backstop_mcp.features.activity_history.fetch_activity_detail import (
    ActivityDetail,
    Attendee,
    MeetingSpecifics,
)
from backstop_mcp.features.activity_history.gist_from_html import to_gist
from backstop_mcp.models import OmitNoneModel

__all__ = ["ActivityDetailResponse", "AttendeeResponse", "to_activity_detail_response"]

# `to_gist` truncates at a word boundary once its squeezed Markdown exceeds this budget. This
# tool's whole point is the FULL body (unlike the timeline's deliberately-truncated gist), so
# the budget is a large constant rather than `len(html)`: markdownify's conversion is expected to
# be same-length-or-shorter than its HTML input, but a constant well beyond any realistic
# activity body doesn't depend on that holding, and costs nothing extra to pick.
_FULL_BODY_MAX_CHARS = 10_000_000


class AttendeeResponse(OmitNoneModel):
    """One trimmed attendee: a single display name (see `Attendee.name`'s fallback)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    name: str | None = Field(default=None, description="Display name of the attendee.")


class ActivityDetailResponse(OmitNoneModel):
    """`get_activity_detail`'s payload: full body plus meeting specifics and attendees.

    `type`, `title` and `body` come from `entity-activity-details`; `start`/`stop`/`location`/
    `time_zone` and `attendees` come from `/meeting-or-calls/{resource_id}`, which is only
    fetched for a meeting-or-calls handle (it 404s for a note or document — see
    `fetch_activity_detail.py`). They are therefore absent for a note or document because nobody
    asked, not because Backstop returned nothing.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, from_attributes=True, extra="ignore"
    )

    activity_id: str = Field(
        description="The activity this detail is for — the same handle that was passed in."
    )
    type: str | None = Field(
        default=None,
        description=(
            "Activity kind as Backstop names it. Omitted for records that do not carry one."
        ),
    )
    title: str | None = Field(default=None, description="Title as Backstop stores it.")
    body: str = Field(
        description=(
            "Full converted markdown of the HTML description — unlike the timeline `gist`, "
            "this is not truncated for a token budget."
        )
    )
    start: datetime | None = Field(
        default=None,
        description="Meeting/call start time. Omitted for a note or document.",
    )
    stop: datetime | None = Field(
        default=None,
        description="Meeting/call end time. Omitted for a note or document.",
    )
    location: str | None = Field(
        default=None,
        description="Meeting/call location. Omitted for a note or document.",
    )
    time_zone: str | None = Field(
        default=None,
        description="Meeting/call time zone. Omitted for a note or document.",
    )
    attendees: list[AttendeeResponse] = Field(
        default_factory=list,
        description="People listed on a meeting/call. Empty for a note or document.",
    )


def to_activity_detail_response(
    *,
    activity_id: str,
    detail: ActivityDetail,
    specifics: MeetingSpecifics | None,
    attendees: tuple[Attendee, ...],
) -> ActivityDetailResponse:
    """Convert the fetched parts to the tool's wire shape. Pure: no HTTP.

    `activity_id` is echoed from the caller's composite handle rather than rebuilt from
    `detail.resource_id`, so what comes back is byte-identical to what went in — and stays a
    handle the model can pass straight back to this tool.
    """
    gist = to_gist(detail.description or "", max_chars=_FULL_BODY_MAX_CHARS)
    return ActivityDetailResponse.model_validate(
        {
            **detail.model_dump(exclude={"resource_id", "description"}),
            **(specifics.model_dump() if specifics is not None else {}),
            "activity_id": activity_id,
            "body": gist.text,
            "attendees": attendees,
        }
    )
