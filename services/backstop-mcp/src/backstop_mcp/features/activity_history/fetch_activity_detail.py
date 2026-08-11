"""Fetch layer for `get_activity_detail`: `entity-activity-details` plus the attendees endpoint.

Unlike every other endpoint this feature talks to, the wire field names here were NOT
byte-verified against a live Backstop instance — the design doc only gives prose descriptions
("start/stop timestamps, location, time_zone" for `entity-activity-details`; "name, firstName,
lastName" for the attendees endpoint), not confirmed JSON spellings. Every attribute below is
therefore optional, every model uses `extra="ignore"`, and every ambiguous field carries a couple
of plausible `AliasChoices` spellings (following the `xxxTimestamp`/camelCase convention this
API's other confirmed fields — `effectiveDate`, `sentTimestamp`, `createdTimestamp` — use) so a
wrong guess degrades to `None`/empty rather than crashing the tool. Guessed aliases, flagged for
live verification:
- `start`/`stop`: `startTimestamp`/`stopTimestamp` (camelCase), `start`/`stop` (bare), and
  `start_timestamp`/`stop_timestamp` (snake_case).
- `location`: `location`, `locationName`, `location_name`.
- `time_zone`: `timeZone`, `time_zone`.
`description` (the full HTML body) and `type` (the meeting/call discriminator) are confirmed by
the design doc, so they carry no aliases.

`activity_id` is the same prefixed id a timeline record already carries (e.g.
`meeting-or-calls_76280387`) — Backstop's own convention elsewhere in this codebase is that a
resource's `id` is what you interpolate directly into a follow-up detail-fetch path. Only a
meeting/call ever carries attendees on this instance, and that shape is always labelled with the
`meeting-or-calls_` prefix (confirmed, not a guess) — `is_meeting_or_call` lets a caller decide
locally, from the id string alone, whether to fetch attendees at all.
"""

import logging
from datetime import datetime
from typing import ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import (
    BackstopApiCollectionDocument,
    BackstopApiResourceDocument,
    BackstopClient,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ActivityDetail",
    "Attendee",
    "fetch_activity_detail",
    "fetch_attendees",
    "is_meeting_or_call",
]

_MEETING_OR_CALL_PREFIX = "meeting-or-calls_"
_ATTENDEE_FIELDS = "name,firstName,lastName"


class _ActivityDetailAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    type: str | None = None
    title: str | None = None
    description: str | None = None
    start: datetime | None = Field(
        default=None, validation_alias=AliasChoices("startTimestamp", "start", "start_timestamp")
    )
    stop: datetime | None = Field(
        default=None, validation_alias=AliasChoices("stopTimestamp", "stop", "stop_timestamp")
    )
    location: str | None = Field(
        default=None, validation_alias=AliasChoices("location", "locationName", "location_name")
    )
    time_zone: str | None = Field(
        default=None, validation_alias=AliasChoices("timeZone", "time_zone")
    )


class _AttendeeAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None
    first_name: str | None = Field(
        default=None, validation_alias=AliasChoices("firstName", "first_name")
    )
    last_name: str | None = Field(
        default=None, validation_alias=AliasChoices("lastName", "last_name")
    )

    def display_name(self) -> str | None:
        """Same "name, else first+last" fallback as `PartyAttributes.display_name()`."""
        if self.name:
            return self.name
        composed = " ".join(part for part in (self.first_name, self.last_name) if part)
        return composed or None


_ActivityDetailDocument = BackstopApiResourceDocument[_ActivityDetailAttributes]
_AttendeeDocument = BackstopApiCollectionDocument[_AttendeeAttributes]


class ActivityDetail(BaseModel):
    """One `entity-activity-details` record.

    Meeting-specific fields are `None` for a note/document.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    type: str | None
    title: str | None
    description: str | None
    start: datetime | None
    stop: datetime | None
    location: str | None
    time_zone: str | None


class Attendee(BaseModel):
    """One trimmed attendee: a single display name, "name, else first+last" (see above)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str | None


def is_meeting_or_call(activity_id: str) -> bool:
    """Whether `activity_id` names a meeting/call — the only shape with attendees.

    Confirmed fact (not a guess): this instance always prefixes meeting/call ids with
    `meeting-or-calls_`, for both meetings and calls, since they're indistinguishable on the
    list endpoint. Notes/documents never carry this prefix.
    """
    return activity_id.startswith(_MEETING_OR_CALL_PREFIX)


async def fetch_activity_detail(client: BackstopClient, *, activity_id: str) -> ActivityDetail:
    """Fetch one activity's full detail record. No `fields=` sparse fieldset: since the exact
    wire spellings for the meeting-specific attributes aren't confirmed, restricting to guessed
    names risks Backstop dropping an attribute that's actually spelled differently — fetching
    the whole record and letting `AliasChoices` sort out the spelling is the safer default.
    """
    logger.debug("activity_history.detail.fetch", extra={"activity_id": activity_id})
    document = await client.get(
        f"/entity-activity-details/{activity_id}",
        schema=_ActivityDetailDocument,
    )
    attributes = document.data.attributes
    detail = ActivityDetail(
        id=document.data.id,
        type=attributes.type,
        title=attributes.title,
        description=attributes.description,
        start=attributes.start,
        stop=attributes.stop,
        location=attributes.location,
        time_zone=attributes.time_zone,
    )
    if is_meeting_or_call(activity_id) and all(
        value is None for value in (detail.start, detail.stop, detail.location, detail.time_zone)
    ):
        logger.debug(
            "activity_history.detail.meeting_fields_empty",
            extra={"activity_id": activity_id, "type": detail.type},
        )
    logger.info(
        "activity_history.detail.fetched",
        extra={
            "activity_id": activity_id,
            "type": detail.type,
            "has_description": detail.description is not None,
        },
    )
    return detail


async def fetch_attendees(client: BackstopClient, *, activity_id: str) -> tuple[Attendee, ...]:
    """Fetch the trimmed attendee list for one meeting/call. Only call when `is_meeting_or_call`."""
    logger.debug("activity_history.attendees.fetch", extra={"activity_id": activity_id})
    document = await client.get(
        f"/meeting-or-calls/{activity_id}/attendees",
        params={"fields": _ATTENDEE_FIELDS},
        schema=_AttendeeDocument,
    )
    attendees = tuple(
        Attendee(name=resource.attributes.display_name()) for resource in document.data
    )
    nameless = sum(1 for attendee in attendees if not attendee.name)
    if nameless:
        logger.debug(
            "activity_history.attendees.nameless",
            extra={"activity_id": activity_id, "nameless": nameless, "total": len(attendees)},
        )
    logger.info(
        "activity_history.attendees.fetched",
        extra={"activity_id": activity_id, "count": len(attendees)},
    )
    return attendees
