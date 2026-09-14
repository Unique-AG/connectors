"""POST a meeting or call as a top-level meeting-or-call.

Same collection, same fields. `kind=meeting` writes `type=FACE_TO_FACE`; `kind=call`
writes `PHONE_OUT` or `PHONE_IN`. The nested `/{segment}/{id}/meetingOrCalls` route 201s
but never appears in the parent's `/activities` feed, so every record goes here with an
explicit `regarding`.

`title`, `type`, `timeZone`, `startTimestamp`, `stopTimestamp`, `regarding` and `author`
are all required by Backstop even where the swagger's required list omits them; the input
model requires the caller-supplied ones so the rejection is a schema error, not a 400.
"""

import logging
from typing import Literal, assert_never

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    isoformat,
    json_api_create,
    omit_none_values,
    relationship_data,
)
from backstop_mcp.features.activity_writes.api_responses import MeetingOrCallAttributes
from backstop_mcp.features.activity_writes.commands._json_api_utils import (
    activity_base_attributes,
    activity_tag_relationship,
    party_resource_link,
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
from backstop_mcp.features.system_users import system_user_relationship
from backstop_mcp.features.time_zones import TimeZonesService

logger = logging.getLogger(__name__)

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
        secondary = secondary_resource_link(
            party_id=party_id,
            secondary_party_id=secondary_party_id,
            secondary_search_type=activity.secondary_search_type,
        )
        payload = json_api_create(
            resource_type="meeting-or-calls",
            attributes=omit_none_values(
                {
                    **activity_base_attributes(activity),
                    "type": self._meeting_type(activity),
                    "location": activity.location,
                    "startTimestamp": isoformat(activity.start),
                    "stopTimestamp": isoformat(activity.stop),
                    "timeZone": time_zone,
                    "regarding": party_resource_link(
                        party_id=party_id, search_type=activity.search_type
                    ),
                    "linkedResources": [secondary] if secondary is not None else None,
                }
            ),
            relationships=self._relationships(activity, author=author),
        )
        document = await self._client.post("/meeting-or-calls", schema=_Document, json=payload)
        resource = document.data
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

    def _relationships(
        self, activity: _MeetingOrCallInput, *, author: AuthorDto
    ) -> dict[str, object]:
        attendees = relationship_data("people", activity.attendee_party_ids or None)
        return omit_none_values(
            {
                "author": system_user_relationship(author.id),
                "attendees": attendees,
                "activityTags": activity_tag_relationship(activity, omit_empty=True),
            }
        )
