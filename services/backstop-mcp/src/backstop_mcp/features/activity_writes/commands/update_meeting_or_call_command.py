"""PATCH a meeting or call via `/meeting-or-calls/{id}`.

`type` is only sent when the caller asked to change it (`kind=call` with an explicit
`direction`). `kind` picks the collection, and meetings and calls share it, so a handle
does not say which one it is: writing `type` unconditionally would silently convert a
`PHONE_IN` call the agent guessed `kind=meeting` for into a face-to-face meeting — the
exact field `get_activity_history` splits calls from meetings on. A PATCH that omits
`type` leaves it untouched (verified live).
"""

import logging
from typing import Literal, assert_never
from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import MeetingOrCallAttributes
from backstop_mcp.features.activity_writes.commands._json_api_utils import (
    activity_base_attributes,
    activity_tag_relationship,
    isoformat,
    json_api_update,
    omit_none_values,
    relationship_data,
)
from backstop_mcp.features.activity_writes.commands.extract_collection import extract_collection
from backstop_mcp.features.activity_writes.responses import UpdatedActivityResponse
from backstop_mcp.features.activity_writes.update_activity_input import (
    UpdateCallInput,
    UpdateMeetingInput,
)
from backstop_mcp.features.time_zones import TimeZonesService
from backstop_mcp.utils import parse_activity_handle

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
        handle = parse_activity_handle(activity.activity_id)
        collection, resource_id = extract_collection(handle, kind=activity.kind)
        path = f"/{collection}/{quote(resource_id, safe='')}"
        time_zone = await self._time_zones_service.resolve_short_name(activity.time_zone)
        payload = json_api_update(
            resource_type=collection,
            resource_id=resource_id,
            attributes=omit_none_values(
                {
                    **activity_base_attributes(activity),
                    "type": self._meeting_type(activity),
                    "location": activity.location,
                    "startTimestamp": isoformat(activity.start),
                    "stopTimestamp": isoformat(activity.stop),
                    "timeZone": time_zone,
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
        """The replacement `type`, or `None` to leave the record's own type alone."""
        match activity.kind:
            case "meeting":
                return None
            case "call":
                return activity.direction
            case _:
                assert_never(activity.kind)

    def _relationships(self, activity: _MeetingOrCallUpdate) -> dict[str, object] | None:
        attendees = relationship_data("people", activity.attendee_party_ids)
        return (
            omit_none_values(
                {
                    "attendees": attendees,
                    "activityTags": activity_tag_relationship(activity),
                }
            )
            or None
        )
