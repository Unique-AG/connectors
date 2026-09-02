"""One activity's detail record, and meeting specifics plus attendees when they apply.

Three endpoints, all keyed by the bare `ResourceIdentifierDto.resource_id` — never the
composite `{resourceType}_{resourceId}` handle. Every field name below was byte-verified
against a live instance:

- `/entity-activity-details/{resource_id}` — `type`, `title`, `description` (full HTML),
  `attachments`. This endpoint answers 200 with null primary data for an unknown id.
- `/meeting-or-calls/{resource_id}` — `startTimestamp`, `stopTimestamp`, `location`,
  `timeZone`. These are not on the detail record. A sparse `fields=` is used.
- `/meeting-or-calls/{resource_id}/attendees` — the trimmed attendee list.

The latter two 404 for a note or document id, so a composite meeting-or-calls handle
gathers all three; any other composite fetches detail only. A bare search id has no
resource type — detail's `type` (`meeting` / `call`) decides the extras. The detail
record's `type` is `"meeting"` for a call as well (verified on a `PHONE_OUT` record).
"""

import asyncio
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
    ResourceIdentifierDto,
    attachments_from_stored,
)
from backstop_mcp.features.activity_history.responses import ActivityDetailResponse

logger = logging.getLogger(__name__)

_ActivityDetailDocument = BackstopApiResourceDocument[ActivityDetailAttributes]
_MeetingSpecificDocument = BackstopApiResourceDocument[MeetingSpecificAttributes]


class GetActivityDetailQuery:
    """Full body, and meeting extras only when the handle or detail type says they apply."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self, *, activity_id: str, handle: ResourceIdentifierDto
    ) -> ActivityDetailResponse:
        """`activity_id` is echoed; `handle` is the already-parsed resource type and id."""
        resource_id = handle.resource_id
        if handle.is_meeting_or_call:
            detail, specifics, attendees = await asyncio.gather(
                self._fetch_activity_detail(resource_id),
                self._fetch_meeting_specifics(resource_id),
                self._attendees(resource_id),
            )
        elif handle.resource_type is not None:
            logger.debug(
                "activity_history.detail.skip_meeting_fetches",
                extra={"activity_id": activity_id, "resource_type": handle.resource_type},
            )
            detail = await self._fetch_activity_detail(resource_id)
            specifics = None
            attendees = ()
        else:
            detail = await self._fetch_activity_detail(resource_id)
            if (detail.type or "").casefold() in {"meeting", "call"}:
                specifics, attendees = await asyncio.gather(
                    self._fetch_meeting_specifics(resource_id),
                    self._attendees(resource_id),
                )
            else:
                specifics = None
                attendees = ()
        return ActivityDetailResponse.from_detail(
            activity_id=activity_id,
            detail=detail,
            specifics=specifics,
            attendees=attendees,
        )

    async def _fetch_activity_detail(self, resource_id: str) -> ActivityDetailDto:
        logger.debug("activity_history.detail.fetch", extra={"resource_id": resource_id})
        path = f"/entity-activity-details/{quote(resource_id, safe='')}"
        document = await self._client.get(path, schema=_ActivityDetailDocument)
        # Null primary data here means "no such activity" — this endpoint answers 200 rather than
        # 404 for an id it cannot resolve, including a composite handle passed through by mistake.
        resource = document.require_data(path=path)
        attributes = resource.attributes
        detail = ActivityDetailDto(
            resource_id=resource.id,
            type=attributes.type,
            title=attributes.title,
            description=attributes.description,
            attachments=attachments_from_stored(attributes.attachments),
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

    async def _fetch_meeting_specifics(self, resource_id: str) -> MeetingSpecificsDto:
        logger.debug("activity_history.meeting_specifics.fetch", extra={"resource_id": resource_id})
        path = f"/meeting-or-calls/{quote(resource_id, safe='')}"
        document = await self._client.get(
            path,
            params={"fields": "startTimestamp,stopTimestamp,location,timeZone"},
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

    async def _attendees(self, resource_id: str) -> tuple[AttendeeDto, ...]:
        logger.debug("activity_history.attendees.fetch", extra={"resource_id": resource_id})
        page = await self._client.paginate(
            f"/meeting-or-calls/{quote(resource_id, safe='')}/attendees",
            params={"fields": "name,firstName,lastName"},
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
