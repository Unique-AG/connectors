"""PATCH a meeting or call via `/meeting-or-calls/{id}`."""

import logging
from typing import Literal, assert_never

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import MeetingOrCallAttributes
from backstop_mcp.features.activity_writes.commands._utils import (
    activity_target,
    isoformat,
    json_api_update,
    omit_none_values,
    relationship_replace,
)
from backstop_mcp.features.activity_writes.responses import UpdatedActivityResponse
from backstop_mcp.features.activity_writes.update_activity_input import (
    UpdateCallInput,
    UpdateMeetingInput,
)
from backstop_mcp.features.time_zones import TimeZonesService

logger = logging.getLogger(__name__)

_Document = BackstopApiSingleResourceDocument[MeetingOrCallAttributes]

type _MeetingType = Literal["FACE_TO_FACE", "PHONE_OUT", "PHONE_IN"]
type _MeetingOrCallUpdate = UpdateMeetingInput | UpdateCallInput


class UpdateMeetingOrCallCommand:
    """Update a meeting or call via `PATCH /meeting-or-calls/{id}`."""

    def __init__(self, *, client: BackstopClient, time_zones_service: TimeZonesService) -> None:
        self._client: BackstopClient = client
        self._time_zones_service: TimeZonesService = time_zones_service

    async def run(self, *, activity: _MeetingOrCallUpdate) -> UpdatedActivityResponse:
        path, resource_id, collection = activity_target(
            kind=activity.kind, activity_id=activity.activity_id
        )
        time_zone = await self._time_zones_service.resolve_short_name(activity.time_zone)
        payload = json_api_update(
            resource_type=collection,
            resource_id=resource_id,
            attributes=omit_none_values(
                {
                    "title": activity.title,
                    "type": self._meeting_type(activity),
                    "location": activity.location,
                    "startTimestamp": isoformat(activity.start),
                    "stopTimestamp": isoformat(activity.stop),
                    "timeZone": time_zone,
                    "effectiveDate": isoformat(activity.effective_date),
                }
            ),
            relationships=self._relationships(activity),
        )
        document = await self._client.patch(path, schema=_Document, json=payload)
        logger.info(
            "activity_writes.meeting_or_call.updated",
            extra={"id": document.data.id, "kind": activity.kind},
        )
        return UpdatedActivityResponse(id=document.data.id, resource_type="meeting-or-calls")

    def _meeting_type(self, activity: _MeetingOrCallUpdate) -> _MeetingType | None:
        match activity.kind:
            case "meeting":
                return "FACE_TO_FACE"
            case "call":
                return activity.direction
            case _:
                assert_never(activity.kind)

    def _relationships(self, activity: _MeetingOrCallUpdate) -> dict[str, object] | None:
        attendees = relationship_replace("people", activity.attendee_party_ids)
        tags = relationship_replace("activity-tags", activity.activity_tag_ids)
        relationships: dict[str, object] = {}
        if attendees is not None:
            relationships["attendees"] = attendees
        if tags is not None:
            relationships["activityTags"] = tags
        return relationships or None
