"""`outlook_cancel_event` — the organizer cancels one event, and Graph mails everyone that it
was cancelled.

- This tool uses one permission, and Microsoft offers no narrower one: `Calendars.ReadWrite`
  (https://learn.microsoft.com/en-us/graph/api/event-cancel).
- Only the organizer can call this tool. This tool reads the event first, and refuses in its
  own words when `isOrganizer` already says no.
- A cancel moves the event to Deleted Items. With any attendee on the event, a cancel also
  sends a cancellation message that this connector cannot recall. An event with nobody on it
  notifies nobody, so this tool skips the question for that case.
- The response is `202 Accepted`, with an empty body. So everything that this tool answers with
  is read before the cancel. This call carries `no_retry()`, because a retried cancel can mail
  the cancellation message to attendees twice.
"""

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

_DESCRIPTION = """\
Cancels one event that the signed-in user organizes, and moves it to Deleted Items. With any \
attendee on the event, this sends them a cancellation message immediately, and nothing here \
can recall it. This tool refuses an event that the signed-in user did not organize. \
outlook_respond_to_invite is the tool for answering an invitation that somebody else organizes.

Notes:
- This tool asks the user to agree before it cancels an event that has any attendee, and \
cancels nothing unless the user agrees. It cancels directly, with no question, only when the \
event currently has nobody on it, because nobody is told either way.
- `comment` is optional text that Microsoft includes in the cancellation message. It reaches \
only attendees that this event already has. It changes nothing when there are none.
- If a call times out, the cancellation and its message can already be out. Before you call \
this tool again, make sure with outlook_list_events that the event is still there.
"""

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
    """This is what this event held just before it was cancelled — the only data that this call
    has, because Microsoft's `202 Accepted` on a successful cancel carries no body."""

    uri: str = Field(
        description=(
            "This is the handle that this call was given, echoed back for a reply about this "
            + "event."
        )
    )
    subject: str | None = Field(
        description=(
            "This is the subject, as it was read just before the cancel. This field is null "
            + "when the event carried none."
        )
    )
    organizer: MailAddress | None = Field(
        description="This is the signed-in user, read off the event before the cancel."
    )
    attendees: list[EventAttendee] = Field(
        description=(
            "This is everyone that this event held just before the cancel, read from that "
            + "pre-cancel state, and never invented. This is who Microsoft mailed the "
            + "cancellation to — or, when this list is empty, the proof that nobody was told, "
            + "because there was nobody to tell."
        )
    )
    comment: str | None = Field(
        description=(
            "This is the comment that this call asked Microsoft to include in the cancellation "
            + "message. This field is null when none was given. Microsoft's 202 says nothing "
            + "about delivery. This is what was requested, and not a receipt."
        )
    )
    notified: bool = Field(
        description=(
            "This is this connector's own inference. It is true when `attendees` was not empty "
            + "just before the cancel. `true` means a cancellation message already went out, "
            + "and CANNOT BE RECALLED here. `false` means the event had nobody on it, so nobody "
            + "was told."
        )
    )


async def cancel_event(
    client: GraphServiceClient,
    *,
    uri: str,
    comment: str | None = None,
    confirm: Confirm,
) -> CancelledEvent | InputRequiredResult:
    """Read the event. Ask a person for confirmation when a cancel would notify anybody. Then
    cancel the event."""
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
                description=(
                    "This is the event to cancel, as the `uri` field of an outlook_list_events "
                    + "or outlook_read_event row, with no change."
                ),
            ),
        ],
        ctx: Context,
        comment: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "This is text that Microsoft includes in the cancellation message. It "
                    + "reaches only attendees that this event already has. Omit this argument "
                    + "for no comment."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> CancelledEvent | InputRequiredResult:
        return await cancel_event(client, uri=uri, comment=comment, confirm=a_person_agrees(ctx))
