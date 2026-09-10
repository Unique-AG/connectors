"""POST a meeting or call as a top-level meeting-or-call.

Same collection, same fields. `kind=meeting` writes `type=FACE_TO_FACE`; `kind=call`
writes `PHONE_OUT` or `PHONE_IN`. The nested `/{segment}/{id}/meetingOrCalls` route 201s
but never appears in the parent's `/activities` feed, so every record goes here with an
explicit `regarding`.
"""

import logging
from typing import Literal, assert_never

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiSingleResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.activity_writes.api_responses import MeetingOrCallAttributes
from backstop_mcp.features.activity_writes.commands._utils import (
    isoformat,
    json_api_create,
    omit_none_values,
    party_resource_link,
    relationship_data,
    secondary_resource_link,
)
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.log_activity_input import (
    CallActivityInput,
    MeetingActivityInput,
)
from backstop_mcp.features.activity_writes.responses import (
    LoggedCallResponse,
    LoggedMeetingResponse,
)
from backstop_mcp.features.system_users import system_user_resource_link
from backstop_mcp.features.time_zones import TimeZonesService

logger = logging.getLogger(__name__)

_PATH = "/meeting-or-calls"
_Document = BackstopApiSingleResourceDocument[MeetingOrCallAttributes]

type _MeetingType = Literal["FACE_TO_FACE", "PHONE_OUT", "PHONE_IN"]
type _MeetingOrCallInput = MeetingActivityInput | CallActivityInput


class LogMeetingOrCallCommand:
    """Create a meeting or call via top-level `POST /meeting-or-calls`."""

    def __init__(self, *, client: BackstopClient, time_zones_service: TimeZonesService) -> None:
        self._client: BackstopClient = client
        self._time_zones_service: TimeZonesService = time_zones_service

    async def run(
        self,
        *,
        activity: _MeetingOrCallInput,
        party_id: str,
        author: AuthorDto,
        secondary_party_id: str | None = None,
    ) -> LoggedMeetingResponse | LoggedCallResponse:
        time_zone = await self._time_zones_service.resolve_short_name(activity.time_zone)
        resource = await self._create(
            activity=activity,
            meeting_type=self._meeting_type(activity),
            party_id=party_id,
            secondary_party_id=secondary_party_id,
            time_zone_short_name=time_zone,
            author=author,
        )
        logger.info(
            "activity_writes.meeting_or_call.created",
            extra={
                "id": resource.id,
                "kind": activity.kind,
                "party_id": party_id,
                "time_zone": time_zone,
            },
        )
        match activity.kind:
            case "meeting":
                return LoggedMeetingResponse(
                    id=resource.id,
                    title=activity.title,
                    time_zone=time_zone,
                )
            case "call":
                return LoggedCallResponse(
                    id=resource.id,
                    title=activity.title,
                    meeting_type=activity.direction,
                    time_zone=time_zone,
                )
            case _:
                assert_never(activity.kind)

    def _meeting_type(self, activity: _MeetingOrCallInput) -> _MeetingType:
        match activity.kind:
            case "meeting":
                return "FACE_TO_FACE"
            case "call":
                return activity.direction
            case _:
                assert_never(activity.kind)

    def _relationships(self, activity: _MeetingOrCallInput) -> dict[str, object] | None:
        attendees = relationship_data("people", activity.attendee_party_ids)
        tags = relationship_data("activity-tags", activity.activity_tag_ids)
        relationships: dict[str, object] = {}
        if attendees is not None:
            relationships["attendees"] = attendees
        if tags is not None:
            relationships["activityTags"] = tags
        return relationships or None

    async def _create(
        self,
        *,
        activity: _MeetingOrCallInput,
        meeting_type: _MeetingType,
        party_id: str,
        secondary_party_id: str | None,
        time_zone_short_name: str,
        author: AuthorDto,
    ) -> BackstopApiResource[MeetingOrCallAttributes]:
        secondary = secondary_resource_link(
            party_id=party_id,
            secondary_party_id=secondary_party_id,
            secondary_search_type=activity.secondary_search_type,
        )
        payload = json_api_create(
            resource_type="meeting-or-calls",
            attributes=omit_none_values(
                {
                    "title": activity.title,
                    "type": meeting_type,
                    "location": activity.location,
                    "startTimestamp": isoformat(activity.start),
                    "stopTimestamp": isoformat(activity.stop),
                    "timeZone": time_zone_short_name,
                    "effectiveDate": isoformat(activity.effective_date),
                    "regarding": party_resource_link(
                        party_id=party_id, search_type=activity.search_type
                    ),
                    "linkedResources": [secondary] if secondary is not None else None,
                    "author": system_user_resource_link(author.id),
                }
            ),
            relationships=self._relationships(activity),
        )
        document = await self._client.post(_PATH, schema=_Document, json=payload)
        return document.data
