"""`outlook_respond_to_invite` — accept, decline, or tentatively accept an invitation you received.

- One permission covers all three actions: `Calendars.ReadWrite`. Microsoft offers no narrower one
  for any of them.
- These are three DISTINCT actions, not one endpoint with a status field. `/accept`, `/decline`,
  and `/tentativelyAccept` are separate Graph operations. This tool calls the one the caller
  named.
- `sendResponse` defaults to `true` and is what actually mails the organizer. This tool exposes
  only `comment`, not `proposedNewTime`: a caller who wants to propose a new time asks the user to
  do that in Outlook.
- Every one of the three returns `202 Accepted` with no body, so nothing here is read back from
  the write. This call carries `no_retry()`, because a retried response can mail the organizer
  twice.
"""

from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.event import Event
from msgraph.generated.users.item.calendars.item.events.item.accept.accept_post_request_body import (  # noqa: E501
    AcceptPostRequestBody,
)
from msgraph.generated.users.item.calendars.item.events.item.decline.decline_post_request_body import (  # noqa: E501
    DeclinePostRequestBody,
)
from msgraph.generated.users.item.calendars.item.events.item.tentatively_accept.tentatively_accept_post_request_body import (  # noqa: E501
    TentativelyAcceptPostRequestBody,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.calendar import confirmation_id_for, event_of
from office_365_mcp.shared.handles import EventHandle, event_handle
from office_365_mcp.shared.mail import MailAddress
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_respond_to_invite"

STEP_RESPOND = "respond_to_invite"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///events/AAMkSYNTHETIC-cal-0001%3D/AAMkAGI2SYNTHETIC-event-0001%3D",
    "response": "accept",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this event, and NO RESPONSE WAS RECORDED. The handle is well "
    + "formed, so this is not a bad argument. The invitation was most likely withdrawn, or the "
    + "event was moved or deleted, and Graph reports all of these with one 404. Before you "
    + "retry, call outlook_list_events again to find out whether the invitation is still there."
)

type Response = Literal["accept", "decline", "tentative"]

# Microsoft's own vocabulary for what got recorded, matching `EventAttendee.response` elsewhere.
_RECORDED_AS: Mapping[Response, str] = {
    "accept": "accepted",
    "decline": "declined",
    "tentative": "tentativelyAccepted",
}

_VERB: Mapping[Response, str] = {
    "accept": "Accept",
    "decline": "Decline",
    "tentative": "Tentatively accept",
}

_AGREE = "respond"
_DECLINE = "do not respond"
_NOTHING_HAPPENED = "No response was sent."

_DESCRIPTION = """\
This tool answers one invitation the signed-in user received, by accepting it, declining it, or \
tentatively accepting it. With `send_response` left at its default of true, this mails the \
organizer immediately, and nothing here can recall it. This tool answers only an invitation \
somebody else organizes. outlook_update_event and outlook_cancel_event are the tools for an \
event the signed-in user organizes.

Notes:
- This tool asks the user to agree before it sends a response that reaches the organizer, and \
sends nothing unless the user agrees. It skips that question only when `send_response` is set to \
false, because then nobody is told either way.
- `comment` is optional text Microsoft includes in the response Microsoft mails the organizer. It \
changes nothing when `send_response` is false.
- This tool cannot propose a different time. If the user wants to suggest one instead of \
answering as asked, tell them to do that from Outlook directly.
- If a call times out, the response can already be sent. Before calling this tool again for the \
same invitation, ask the user whether they already answered it in Outlook.
"""

_NOT_A_HANDLE = (
    "outlook_respond_to_invite takes the `uri` that outlook_list_events or outlook_read_event "
    + "reported, and this is not one. A readable event handle has exactly one shape:\n"
    + "  outlook:///events/{calendar_id}/{event_id}\n"
    + "with both ids percent-encoded. NO RESPONSE WAS SENT. Copy the `uri` of a tool result, "
    + "rather than assembling one. Retrying this value will fail identically."
)


class InvitationResponse(BaseModel):
    """What this call asked Microsoft to record. Every one of the three actions answers `202
    Accepted` with an empty body. Nothing here is confirmed by reading Microsoft's response. This
    is what this call requested, read against the event as it stood just before this call."""

    uri: str = Field(
        description="The handle this call was given, echoed back for a reply about this event."
    )
    subject: str | None = Field(
        description=(
            "The subject as it was read just before this call. Null when the event carried "
            + "none."
        )
    )
    organizer: MailAddress | None = Field(
        description=(
            "Who organizes this event, read off the event before this call. This is who "
            + "Microsoft mails the response to when `sent_response` is true."
        )
    )
    response: str = Field(
        description=(
            "What this call asked Microsoft to record, in Microsoft's own spelling: "
            + "`accepted`, `declined`, or `tentativelyAccepted`. This matches the vocabulary "
            + "`outlook_read_event` reports for an attendee's own answer."
        )
    )
    comment: str | None = Field(description="The comment this call sent. Null when none was given.")
    sent_response: bool = Field(
        description=(
            "Whether this call asked Microsoft to mail the organizer, echoed from the "
            + "`send_response` argument. True means that mail already went out and CANNOT BE "
            + "RECALLED here. Microsoft's 202 confirms nothing further about delivery. This is "
            + "what was requested, not a receipt."
        )
    )


async def respond_to_invite(
    client: GraphServiceClient,
    *,
    uri: str,
    response: Response,
    comment: str | None = None,
    send_response: bool = True,
    confirm: Confirm,
) -> InvitationResponse | InputRequiredResult:
    """Read the event, ask a person when this response reaches the organizer, then send it."""
    handle = event_handle(uri)
    if handle is None:
        raise ToolError(_NOT_A_HANDLE)

    asked: InputRequiredResult | None = None
    refused: str | None = None
    about = confirmation_id_for(handle.uri, response, repr(comment), repr(send_response))
    with graph_errors(TOOL_NAME):
        event = await event_of(client, calendar_id=handle.calendar_id, event_id=handle.event_id)
        if send_response:
            with not_graph():
                answer = await confirm(_question(event, response, comment), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_RESPOND):
                await _sent(
                    client,
                    handle,
                    response,
                    comment=comment,
                    send_response=send_response,
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return _answer(handle, event, response, comment=comment, send_response=send_response)


async def _sent(
    client: GraphServiceClient,
    handle: EventHandle,
    response: Response,
    *,
    comment: str | None,
    send_response: bool,
) -> None:
    events = client.me.calendars.by_calendar_id(handle.calendar_id).events.by_event_id(
        handle.event_id
    )
    configuration = RequestConfiguration[QueryParameters](options=no_retry())
    if response == "accept":
        await events.accept.post(
            AcceptPostRequestBody(comment=comment, send_response=send_response),
            request_configuration=configuration,
        )
    elif response == "decline":
        await events.decline.post(
            DeclinePostRequestBody(comment=comment, send_response=send_response),
            request_configuration=configuration,
        )
    else:
        await events.tentatively_accept.post(
            TentativelyAcceptPostRequestBody(comment=comment, send_response=send_response),
            request_configuration=configuration,
        )


def _question(event: Event, response: Response, comment: str | None) -> str:
    name = event.subject or "this event"
    organizer = event.organizer
    address = organizer.email_address.address if organizer and organizer.email_address else None
    to = address or "the organizer"
    said = f" ({comment!r})" if comment else ""
    return (
        f"{_VERB[response]} {name!r}? Microsoft mails{said} {to}, and this connector cannot "
        + "recall it."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_HAPPENED)


def _answer(
    handle: EventHandle,
    event: Event,
    response: Response,
    *,
    comment: str | None,
    send_response: bool,
) -> InvitationResponse:
    return InvitationResponse(
        uri=handle.uri,
        subject=event.subject,
        organizer=MailAddress.from_recipient(event.organizer),
        response=_RECORDED_AS[response],
        comment=comment,
        sent_response=send_response,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Respond to a Calendar Invitation",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def outlook_respond_to_invite(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The invitation to answer, as the `uri` field of an outlook_list_events or "
                    + "outlook_read_event row, verbatim."
                ),
            ),
        ],
        response: Annotated[
            Response,
            Field(
                description=(
                    "How to answer: `accept`, `decline`, or `tentative`. These are three "
                    + "distinct Microsoft Graph actions, and this tool calls the one that "
                    + "matches."
                )
            ),
        ],
        ctx: Context,
        comment: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Text Microsoft includes in the response mailed to the organizer. Reaches "
                    + "nobody when `send_response` is false. Omit for no comment."
                ),
            ),
        ] = None,
        send_response: Annotated[
            bool,
            Field(
                description=(
                    "Set this to false to record the answer without mailing the organizer. "
                    + "Left at its default of true, this call mails the organizer immediately."
                )
            ),
        ] = True,
        client: GraphServiceClient = graph,
    ) -> InvitationResponse | InputRequiredResult:
        return await respond_to_invite(
            client,
            uri=uri,
            response=response,
            comment=comment,
            send_response=send_response,
            confirm=a_person_agrees(ctx),
        )
