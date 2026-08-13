"""Wire response models for an activity-history tool payload, and the pure conversion from an
already-merged record (`ActivityWithType`) to its wire shape (`TimelineRecord`).

Standing caveats (documents excluded from the token budget concerns, same-day email-vs-activity
ordering, the meaning of `activity_types`) belong in the tool description, not in this payload —
see the design doc's "Token budget" section. This module carries no prose `notes` field.

`resource_type` is deliberately never surfaced: for meeting/call it is always the literal,
uninformative string `"meeting-or-calls"` (`stream` already says which), and notes/documents
don't reliably carry a derivable prefix at all (see `fetch_activities.py`'s module docstring).
`resource_id` is kept — a real pointer a future detail/documents tool can use.

Field renames (`id`→`activity_id`, `effective_date`/`sent_timestamp`→`occurred_at`) use
`validation_alias` + `from_attributes`. Gist conversion, recipient capping, and the
`stream`→`type` assignment (kept explicit: discriminators reject aliases on `type`) stay in
`to_timeline_record`.
"""

import logging
from datetime import date, datetime
from typing import Annotated, ClassVar, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from backstop_mcp.features.activity_history.fetch_activities import (
    ActivityItem,
    BackstopActivityType,
    EmailItem,
)
from backstop_mcp.features.activity_history.gist_from_html import to_gist
from backstop_mcp.features.activity_history.merge import ActivityWithType
from backstop_mcp.features.data_hygiene import AsOf, EmploymentLinkResponse
from backstop_mcp.features.party_resolver import PartyAmbiguousResponse, ResolvedPartyResponse
from backstop_mcp.features.resolution import NotFoundResponse

logger = logging.getLogger(__name__)

__all__ = [
    "ActivityHistoryResolvedResponse",
    "ActivityRecordResponse",
    "EmailRecordResponse",
    "GetActivityHistoryResponse",
    "TimelineRecord",
    "to_timeline_record",
]

_MAX_RECIPIENTS = 3


class ActivityRecordResponse(BaseModel):
    """One meeting/call/note/document record on the timeline."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True, extra="ignore")

    # Plain field name required: pydantic discriminators reject AliasChoices on `type`.
    type: BackstopActivityType
    activity_id: str = Field(validation_alias=AliasChoices("activity_id", "id"))
    resource_id: str | None = None
    occurred_at: date | None = Field(
        default=None, validation_alias=AliasChoices("occurred_at", "effective_date")
    )
    title: str | None = None
    gist: str | None = None
    gist_truncated: bool = False
    description_length: int | None = None


class EmailRecordResponse(BaseModel):
    """One email record on the timeline. No gist: emails carry no HTML body to convert."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True, extra="ignore")

    type: Literal["email"] = "email"
    activity_id: str = Field(validation_alias=AliasChoices("activity_id", "id"))
    occurred_at: datetime | None = Field(
        default=None, validation_alias=AliasChoices("occurred_at", "sent_timestamp")
    )
    subject: str | None = None
    from_email: str | None = None
    to_emails: tuple[str, ...] = ()
    to_emails_count: int | None = None
    cc_emails: tuple[str, ...] = ()
    cc_emails_count: int | None = None
    has_attachments: bool | None = None


type TimelineRecord = Annotated[
    ActivityRecordResponse | EmailRecordResponse, Field(discriminator="type")
]


def _cap_recipients(emails: tuple[str, ...]) -> tuple[tuple[str, ...], int | None]:
    """First three addresses, plus a count populated only when something was dropped."""
    if len(emails) <= _MAX_RECIPIENTS:
        return emails, None
    logger.debug(
        "activity_history.recipients.capped",
        extra={"total": len(emails), "kept": _MAX_RECIPIENTS},
    )
    return emails[:_MAX_RECIPIENTS], len(emails)


def to_timeline_record(merged: ActivityWithType, *, gist_max_chars: int) -> TimelineRecord:
    """Convert one merged record to its wire shape. Pure: no HTTP, no config lookups."""
    if merged.stream == "email":
        item = merged.item
        assert isinstance(item, EmailItem), "stream 'email' must carry an EmailItem"
        to_emails, to_emails_count = _cap_recipients(item.to_emails)
        cc_emails, cc_emails_count = _cap_recipients(item.cc_emails)
        return EmailRecordResponse.model_validate(item).model_copy(
            update={
                "to_emails": to_emails,
                "to_emails_count": to_emails_count,
                "cc_emails": cc_emails,
                "cc_emails_count": cc_emails_count,
            }
        )

    item = merged.item
    assert isinstance(item, ActivityItem), f"stream {merged.stream!r} must carry an ActivityItem"
    gist = to_gist(item.description or "", max_chars=gist_max_chars)
    return ActivityRecordResponse.model_validate(
        {
            **item.model_dump(),
            "type": item.stream,
            "gist": gist.text,
            "gist_truncated": gist.truncated,
            "description_length": gist.full_length if gist.truncated else None,
        }
    )


class ActivityHistoryResolvedResponse(BaseModel):
    """`get_activity_history` once the party was resolved and its timeline fetched.

    `employments` lists current and former person↔organization links from side-loaded
    `entityRelationships` on either a person or an organization party.
    """

    status: Literal["resolved"] = "resolved"
    resolved: ResolvedPartyResponse
    records: list[TimelineRecord]
    next_cursor: str | None = None
    as_of: AsOf | None = None
    employments: list[EmploymentLinkResponse] = Field(default_factory=list)


type GetActivityHistoryResponse = (
    PartyAmbiguousResponse | NotFoundResponse | ActivityHistoryResolvedResponse
)
