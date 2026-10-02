from collections.abc import Mapping
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.event import Event
from msgraph.generated.models.event_type import EventType
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.calendar import (
    SERIES_MASTER_FIELD,
    EventAttendee,
    EventTime,
    confirmation_id_for,
    event_of,
    event_time,
    series_reach,
)
from office_365_mcp.shared.handles import EventHandle, event_handle
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_delete_event"

STEP_DELETE = "delete_event"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///events/AAMkSYNTHETIC-cal-0001%3D/AAMkAGI2SYNTHETIC-event-0001%3D",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this event, and this call deleted nothing. The handle is well "
    + "formed, so this is not a bad argument. The event is probably already gone. An earlier call "
    + "of this tool or a person deleted it, or it moved to another calendar. Graph also reports "
    + "an event that the signed-in user cannot see with the same 404. Call outlook_list_events "
    + "again to find out whether the event is still there. If you call this tool again with the "
    + "same arguments, the call will fail the same way."
)

_AGREE = "delete"
_DECLINE = "keep the event"
_NOTHING_DELETED = "The event was not deleted."

_UTC = ZoneInfo("UTC")

_DESCRIPTION = """\
Deletes one event that the signed-in user organizes, from the calendar that holds it. If the \
event has attendees, Microsoft sends each attendee a cancellation. outlook_cancel_event also \
sends a cancellation, but it can add a comment, and it moves the event to Deleted Items. \
outlook_respond_to_invite declines an event that somebody else organizes.

Notes:
- This tool always asks the user to agree, because Microsoft does not document whether a deleted \
event can be restored. The question names the subject, the start, and each attendee.
- This tool refuses an event that the signed-in user does not organize. Microsoft does not \
document what a delete of the copy of an attendee does for the organizer.
- This call is safe to repeat after a timeout. A second call finds no event and reports that.
"""

_NOT_A_HANDLE = (
    "outlook_delete_event takes the `uri` that outlook_list_events or outlook_read_event "
    + "reported, and this is not one. An event handle has exactly one shape:\n"
    + "  outlook:///events/{calendar_id}/{event_id}\n"
    + "with both ids percent-encoded. The event was not deleted. Copy the `uri` of a tool result, "
    + "and do not assemble one. If you call this tool again with the same arguments, the call "
    + "will fail the same way."
)

_NOT_THE_ORGANIZER = (
    "Microsoft 365 does not report the signed-in user as the organizer of this event. The event "
    + "was not deleted. Microsoft documents the effect of a delete only on the calendar of the "
    + "organizer, where each attendee gets a cancellation. Microsoft does not document what a "
    + "delete of the copy of an attendee does for the organizer. If the user no longer wants to "
    + "attend, outlook_respond_to_invite can decline the invitation and tell the organizer. If "
    + "you call this tool again with the same arguments, the call will fail the same way."
)


class DeletedEvent(BaseModel):
    uri: str = Field(
        description=(
            "The event handle that this call was given, echoed back. Microsoft removed this "
            + "event from the calendar that holds it."
        )
    )
    subject: str | None = Field(
        description=(
            "The subject of the event, as this tool read it just before the delete. The value "
            + "is null when the event had no subject."
        )
    )
    start: EventTime | None = Field(
        description=(
            "When the event starts, as this tool read it just before the delete. The value is "
            + "null when Graph reported no start for the event."
        )
    )
    series_master: bool = Field(description=SERIES_MASTER_FIELD)
    attendees: list[EventAttendee] = Field(
        description=(
            "Each attendee that the event held just before the delete. Microsoft sent each of "
            + "them a cancellation. The list is empty when the event had no attendees."
        )
    )


async def delete_event(
    client: GraphServiceClient, *, uri: str, confirm: Confirm
) -> DeletedEvent | InputRequiredResult:
    handle = event_handle(uri)
    if handle is None:
        raise ToolError(_NOT_A_HANDLE)

    asked: InputRequiredResult | None = None
    about = confirmation_id_for(handle.uri, TOOL_NAME)
    with graph_errors(TOOL_NAME):
        event = await event_of(client, calendar_id=handle.calendar_id, event_id=handle.event_id)
        refused = _NOT_THE_ORGANIZER if event.is_organizer is not True else None
        if refused is None:
            with not_graph():
                answer = await confirm(_question(event), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_DELETE):
                await (
                    client.me.calendars.by_calendar_id(handle.calendar_id)
                    .events.by_event_id(handle.event_id)
                    .delete(
                        request_configuration=RequestConfiguration[QueryParameters](
                            options=no_retry()
                        )
                    )
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return _answer(handle, event)


def _question(event: Event) -> str:
    named = repr(cut_for_a_question(event.subject)) if event.subject else "with no subject"
    start = event_time(event.start, zone=_UTC)
    starting = "" if start is None else f" that starts {start.iso or start.local}"
    reach = series_reach(event, what="delete")
    series = f" {reach}" if reach else ""
    invited = [
        one.address or one.name or "an attendee" for one in EventAttendee.each_of(event.attendees)
    ]
    mailed = (
        f" Microsoft mails a cancellation to {', '.join(invited)}, and this connector cannot "
        + "recall it."
        if invited
        else ""
    )
    return (
        f"Delete the event {named}{starting}?{series}{mailed} Microsoft does not document whether "
        + "a deleted event can be restored."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def _answer(handle: EventHandle, event: Event) -> DeletedEvent:
    return DeletedEvent(
        uri=handle.uri,
        subject=event.subject,
        start=event_time(event.start, zone=_UTC),
        series_master=event.type == EventType.SeriesMaster,
        attendees=EventAttendee.each_of(event.attendees),
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Delete a Calendar Event",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_event(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The event to delete, as the `uri` of an outlook_list_events row or of an "
                    + "outlook_read_event answer, copied word for word. The shape is "
                    + "outlook:///events/{calendar_id}/{event_id}."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedEvent | InputRequiredResult:
        return await delete_event(client, uri=uri, confirm=a_person_agrees(ctx))
