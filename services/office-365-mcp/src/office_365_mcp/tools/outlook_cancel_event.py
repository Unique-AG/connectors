from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.attendee import Attendee
from msgraph.generated.models.event import Event
from msgraph.generated.users.item.calendars.item.events.item.cancel.cancel_post_request_body import (  # noqa: E501
    CancelPostRequestBody,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.calendar import EventAttendee, confirmation_id_for, event_of
from office_365_mcp.shared.handles import EventHandle, event_handle
from office_365_mcp.shared.mail import MailAddress
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_cancel_event"

STEP_CANCEL = "cancel_event"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///events/AAMkSYNTHETIC-cal-0001%3D/AAMkAGI2SYNTHETIC-event-0001%3D",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this event, and NOTHING WAS CANCELLED. The handle is well "
    + "formed, so this is not a bad argument: the event was most likely already deleted, or "
    + "moved to another calendar, or the signed-in user can no longer see it, and Graph reports "
    + "all three with one 404. Call outlook_list_events again to check whether it is still there "
    + "before retrying."
)

_AGREE = "cancel"
_DECLINE = "do not cancel"
_NOTHING_HAPPENED = "Nothing was cancelled."

_DESCRIPTION = (
    "Cancels one event that the signed-in user organizes, moves it to Deleted Items, and mails "
    + "any attendees a cancellation. Refuses an event the signed-in user did not organize."
)

_NOT_A_HANDLE = (
    "outlook_cancel_event takes the `uri` that outlook_list_events or outlook_read_event reported, "
    + "and this is not one. A readable event handle has exactly one shape:\n"
    + "  outlook:///events/{calendar_id}/{event_id}\n"
    + "with both ids percent-encoded. NOTHING WAS CANCELLED. Copy the `uri` of a tool result, "
    + "rather than assembling one. Retrying this value will fail identically."
)

_NOT_THE_ORGANIZER = (
    "Microsoft 365 records the signed-in user as an attendee of this event, not its organizer, "
    + "and only the organizer can cancel it: 'You need to be an organizer to cancel a meeting.' "
    + "NOTHING WAS CANCELLED. If the user no longer wants to attend, outlook_respond_to_invite "
    + "can decline the invitation instead — that notifies the organizer rather than cancelling "
    + "their event out from under them. Retrying will fail identically."
)


class CancelledEvent(BaseModel):
    uri: str = Field(description="The handle this call was given, echoed back.")
    subject: str | None = Field(
        description="The subject as read just before the cancel, or null if none."
    )
    organizer: MailAddress | None = Field(
        description="The signed-in user, read off the event before the cancel."
    )
    attendees: list[EventAttendee] = Field(
        description="Everyone this event held just before the cancel."
    )
    comment: str | None = Field(
        description="The comment sent with the cancellation, or null if none."
    )
    notified: bool = Field(
        description="Whether a cancellation message went out; true when `attendees` was not empty."
    )


async def cancel_event(
    client: GraphServiceClient,
    *,
    uri: str,
    comment: str | None = None,
    confirm: Confirm,
) -> CancelledEvent | InputRequiredResult:
    handle = event_handle(uri)
    if handle is None:
        raise ToolError(_NOT_A_HANDLE)

    asked: InputRequiredResult | None = None
    about = confirmation_id_for(handle.uri, repr(comment))
    with graph_errors(TOOL_NAME):
        event = await event_of(client, calendar_id=handle.calendar_id, event_id=handle.event_id)
        refused = _NOT_THE_ORGANIZER if event.is_organizer is False else None
        if refused is None and event.attendees:
            with not_graph():
                answer = await confirm(_question(event, comment), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_CANCEL):
                await (
                    client.me.calendars.by_calendar_id(handle.calendar_id)
                    .events.by_event_id(handle.event_id)
                    .cancel.post(
                        CancelPostRequestBody(comment=comment),
                        request_configuration=RequestConfiguration[QueryParameters](
                            options=no_retry()
                        ),
                    )
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return _answer(handle, event, comment=comment)


def _question(event: Event, comment: str | None) -> str:
    invited = [_named(attendee) for attendee in event.attendees or []]
    name = event.subject or "this event"
    said = f" ({comment!r})" if comment else ""
    return (
        f"Cancel {name!r}? Microsoft mails a cancellation{said} to {', '.join(invited)}, and this "
        + "connector cannot recall it."
    )


def _named(attendee: Attendee) -> str:
    email = attendee.email_address
    if email is None:
        return "an attendee"
    return email.address or email.name or "an attendee"


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_HAPPENED)


def _answer(handle: EventHandle, event: Event, *, comment: str | None) -> CancelledEvent:
    stored = EventAttendee.each_of(event.attendees)
    return CancelledEvent(
        uri=handle.uri,
        subject=event.subject,
        organizer=MailAddress.from_recipient(event.organizer),
        attendees=stored,
        comment=comment,
        notified=bool(stored),
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Cancel a Calendar Event",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def outlook_cancel_event(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description="The event to cancel, as an outlook_list_events or outlook_read_event "
                + "row's `uri`.",
            ),
        ],
        ctx: Context,
        comment: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Text to include in the cancellation message. Omit for no comment.",
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> CancelledEvent | InputRequiredResult:
        return await cancel_event(client, uri=uri, comment=comment, confirm=a_person_agrees(ctx))
