"""Fetch layer for `get_activity_detail`: the detail record, meeting specifics, and attendees.

Three endpoints, all keyed by the **bare** `ActivityHandle.resource_id` — the
`specificResource.resourceId` a timeline record already carries — never the composite
`{resourceType}_{resourceId}` handle the `/activities` view uses for its own resource ids (see
`activity_handle.py`). Every field name below was byte-verified against a live instance:

- `/entity-activity-details/{resource_id}` — `type`, `title` and `description` (the full HTML
  body), for any activity kind. It carries nothing else worth reading: the whole attribute set is
  `attachments`, `fbId`, `description`, `type`, `title`, plus `attachedTo` on a document.
- `/meeting-or-calls/{resource_id}` — `startTimestamp`, `stopTimestamp`, `location` and
  `timeZone`. These live here and NOT on the detail record, which is why they are a separate
  fetch; a sparse `fields=` works, so only those four are requested.
- `/meeting-or-calls/{resource_id}/attendees` — the trimmed attendee list.

The latter two are valid only for a `meeting-or-calls` handle — both 404 for a note's or a
document's resource id — so `ActivityHandle.is_meeting_or_call` gates them.

Known Backstop imprecision, deliberately passed through rather than papered over: the detail
record's `type` is `"meeting"` for a call as well as a meeting (verified on a `PHONE_OUT` record),
so it does not distinguish the two the way the timeline's own `type` does. Only
`/meeting-or-calls/{id}`'s `type` (`FACE_TO_FACE`, `PHONE_OUT`, ...) does, and this layer does not
request it.
"""

import logging
from datetime import datetime
from typing import ClassVar
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ActivityDetail",
    "Attendee",
    "MeetingSpecifics",
    "fetch_activity_detail",
    "fetch_attendees",
    "fetch_meeting_specifics",
]

_ATTENDEE_FIELDS = "name,firstName,lastName"
_MEETING_SPECIFIC_FIELDS = "startTimestamp,stopTimestamp,location,timeZone"


class _ActivityDetailAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    type: str | None = None
    title: str | None = None
    description: str | None = None


class _MeetingSpecificAttributes(BaseModel):
    # `populate_by_name` so the aliased fields can also be set by their Python name in a plain
    # keyword constructor call, not only through `model_validate` of a wire payload.
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    start: datetime | None = Field(default=None, validation_alias="startTimestamp")
    stop: datetime | None = Field(default=None, validation_alias="stopTimestamp")
    location: str | None = None
    time_zone: str | None = Field(default=None, validation_alias="timeZone")


class _AttendeeAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: str | None = None
    first_name: str | None = Field(default=None, validation_alias="firstName")
    last_name: str | None = Field(default=None, validation_alias="lastName")

    def display_name(self) -> str | None:
        """Same "name, else first+last" fallback as `PartyAttributes.display_name()`."""
        if self.name:
            return self.name
        composed = " ".join(part for part in (self.first_name, self.last_name) if part)
        return composed or None


_ActivityDetailDocument = BackstopApiResourceDocument[_ActivityDetailAttributes]
_MeetingSpecificDocument = BackstopApiResourceDocument[_MeetingSpecificAttributes]


class ActivityDetail(BaseModel):
    """One `entity-activity-details` record — what Backstop stores for any activity kind."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    resource_id: str
    type: str | None
    title: str | None
    description: str | None


class MeetingSpecifics(BaseModel):
    """When and where one meeting/call happened, from `/meeting-or-calls/{resource_id}`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    start: datetime | None
    stop: datetime | None
    location: str | None
    time_zone: str | None


class Attendee(BaseModel):
    """One trimmed attendee: a single display name, "name, else first+last" (see above)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str | None


async def fetch_activity_detail(client: BackstopClient, *, resource_id: str) -> ActivityDetail:
    """Fetch one activity's detail record by its bare resource id.

    No `fields=` sparse fieldset: the record is five attributes wide, so restricting it saves
    nothing worth the extra failure mode.
    """
    logger.debug("activity_history.detail.fetch", extra={"resource_id": resource_id})
    path = f"/entity-activity-details/{quote(resource_id, safe='')}"
    document = await client.get(path, schema=_ActivityDetailDocument)
    # Null primary data here means "no such activity" — this endpoint answers 200 rather than
    # 404 for an id it cannot resolve, including a composite handle passed through by mistake.
    resource = document.require_data(path=path)
    attributes = resource.attributes
    detail = ActivityDetail(
        resource_id=resource.id,
        type=attributes.type,
        title=attributes.title,
        description=attributes.description,
    )
    logger.info(
        "activity_history.detail.fetched",
        extra={
            "resource_id": resource_id,
            "type": detail.type,
            "has_description": detail.description is not None,
        },
    )
    return detail


async def fetch_meeting_specifics(client: BackstopClient, *, resource_id: str) -> MeetingSpecifics:
    """Fetch one meeting/call's timings and location. Only call for a meeting-or-calls handle."""
    logger.debug("activity_history.meeting_specifics.fetch", extra={"resource_id": resource_id})
    path = f"/meeting-or-calls/{quote(resource_id, safe='')}"
    document = await client.get(
        path,
        params={"fields": _MEETING_SPECIFIC_FIELDS},
        schema=_MeetingSpecificDocument,
    )
    attributes = document.require_data(path=path).attributes
    specifics = MeetingSpecifics(
        start=attributes.start,
        stop=attributes.stop,
        location=attributes.location,
        time_zone=attributes.time_zone,
    )
    logger.info(
        "activity_history.meeting_specifics.fetched",
        extra={
            "resource_id": resource_id,
            "has_start": specifics.start is not None,
            "has_location": specifics.location is not None,
        },
    )
    return specifics


async def fetch_attendees(client: BackstopClient, *, resource_id: str) -> tuple[Attendee, ...]:
    """Fetch the trimmed attendee list for one meeting/call by its bare resource id."""
    logger.debug("activity_history.attendees.fetch", extra={"resource_id": resource_id})
    page = await client.paginate(
        f"/meeting-or-calls/{quote(resource_id, safe='')}/attendees",
        params={"fields": _ATTENDEE_FIELDS},
        schema=BackstopApiResource[_AttendeeAttributes],
        max_records=None,
    )
    attendees = tuple(Attendee(name=resource.attributes.display_name()) for resource in page.items)
    nameless = sum(1 for attendee in attendees if not attendee.name)
    if nameless:
        logger.debug(
            "activity_history.attendees.nameless",
            extra={"resource_id": resource_id, "nameless": nameless, "total": len(attendees)},
        )
    logger.info(
        "activity_history.attendees.fetched",
        extra={"resource_id": resource_id, "count": len(attendees)},
    )
    return attendees
