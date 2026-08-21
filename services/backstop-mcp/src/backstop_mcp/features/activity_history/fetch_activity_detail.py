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
from urllib.parse import quote

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.activity_history.api_responses import (
    ActivityDetailAttributes,
    AttendeeAttributes,
    MeetingSpecificAttributes,
)
from backstop_mcp.features.activity_history.internal_dto import (
    ActivityDetailDto,
    AttendeeDto,
    MeetingSpecificsDto,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ActivityDetailDto",
    "AttendeeDto",
    "MeetingSpecificsDto",
    "fetch_activity_detail",
    "fetch_attendees",
    "fetch_meeting_specifics",
]

_ATTENDEE_FIELDS = "name,firstName,lastName"
_MEETING_SPECIFIC_FIELDS = "startTimestamp,stopTimestamp,location,timeZone"


_ActivityDetailDocument = BackstopApiResourceDocument[ActivityDetailAttributes]
_MeetingSpecificDocument = BackstopApiResourceDocument[MeetingSpecificAttributes]


async def fetch_activity_detail(client: BackstopClient, *, resource_id: str) -> ActivityDetailDto:
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
    detail = ActivityDetailDto(
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


async def fetch_meeting_specifics(
    client: BackstopClient, *, resource_id: str
) -> MeetingSpecificsDto:
    """Fetch one meeting/call's timings and location. Only call for a meeting-or-calls handle."""
    logger.debug("activity_history.meeting_specifics.fetch", extra={"resource_id": resource_id})
    path = f"/meeting-or-calls/{quote(resource_id, safe='')}"
    document = await client.get(
        path,
        params={"fields": _MEETING_SPECIFIC_FIELDS},
        schema=_MeetingSpecificDocument,
    )
    attributes = document.require_data(path=path).attributes
    specifics = MeetingSpecificsDto(
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


async def fetch_attendees(client: BackstopClient, *, resource_id: str) -> tuple[AttendeeDto, ...]:
    """Fetch the trimmed attendee list for one meeting/call by its bare resource id."""
    logger.debug("activity_history.attendees.fetch", extra={"resource_id": resource_id})
    page = await client.paginate(
        f"/meeting-or-calls/{quote(resource_id, safe='')}/attendees",
        params={"fields": _ATTENDEE_FIELDS},
        schema=BackstopApiResource[AttendeeAttributes],
        max_records=None,
    )
    attendees = tuple(
        AttendeeDto(name=resource.attributes.display_name()) for resource in page.items
    )
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
