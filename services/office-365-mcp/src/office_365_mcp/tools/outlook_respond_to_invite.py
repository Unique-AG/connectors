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

_DESCRIPTION = (
    "Accept, decline, or tentatively accept a calendar invitation the signed-in user received, "
    "by default notifying the organizer."
)

_NOT_A_HANDLE = (
    "outlook_respond_to_invite takes the `uri` that outlook_list_events or outlook_read_event "
    + "reported, and this is not one. A readable event handle has exactly one shape:\n"
    + "  outlook:///events/{calendar_id}/{event_id}\n"
    + "with both ids percent-encoded. NO RESPONSE WAS SENT. Copy the `uri` of a tool result, "
    + "rather than assembling one. Retrying this value will fail identically."
)


class InvitationResponse(BaseModel):
    uri: str = Field(description="The event handle this call was given.")
    subject: str | None = Field(description="The event's subject, or null if it had none.")
    organizer: MailAddress | None = Field(description="Who organizes this event.")
    response: str = Field(
        description="What was recorded: accepted, declined, or tentativelyAccepted."
    )
    comment: str | None = Field(description="The comment that was sent, or null if none.")
    sent_response: bool = Field(description="Whether the organizer was notified.")


async def respond_to_invite(
    client: GraphServiceClient,
    *,
    uri: str,
    response: Response,
    comment: str | None = None,
    send_response: bool = True,
    confirm: Confirm,
) -> InvitationResponse | InputRequiredResult:
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
                description="The invitation's uri, from outlook_list_events or outlook_read_event.",
            ),
        ],
        response: Annotated[
            Response,
            Field(description="How to answer: accept, decline, or tentative."),
        ],
        ctx: Context,
        comment: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Optional text included in the response mailed to the organizer.",
            ),
        ] = None,
        send_response: Annotated[
            bool,
            Field(description="Whether to notify the organizer. Defaults to true."),
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
