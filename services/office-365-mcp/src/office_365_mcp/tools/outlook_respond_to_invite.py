from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.event import Event
from msgraph.generated.models.time_slot import TimeSlot
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
from office_365_mcp.shared.calendar import ZONE_NAME, confirmation_id_for, event_of, wall_clock
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

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_read_event",)

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

_PROPOSAL_FIELDS: tuple[str, ...] = ("allowNewTimeProposals",)

_DESCRIPTION = """\
Accepts, declines, or tentatively accepts one calendar invitation that the signed-in user \
received. With a decline or a tentative response, this tool can also propose a new time to the \
organizer. By default, this tool sends the response to the organizer immediately, and nothing \
here can recall it. outlook_cancel_event is the tool that cancels an event that the user organizes.

Notes:
- This tool asks the user to agree before it sends a response to the organizer. This tool sends \
nothing unless the user agrees. This tool records a response without that agreement only when \
`send_response` is false. Microsoft then tells the organizer nothing.
- If a call times out, do not call this tool again first. A response can already be out. Before \
you respond again, make sure that outlook_read_event does not already show it in `owner_response`.
"""

_NOT_A_HANDLE = (
    "outlook_respond_to_invite takes the `uri` that outlook_list_events or outlook_read_event "
    + "reported, and this is not one. A readable event handle has exactly one shape:\n"
    + "  outlook:///events/{calendar_id}/{event_id}\n"
    + "with both ids percent-encoded. NO RESPONSE WAS SENT. Copy the `uri` of a tool result, "
    + "rather than assembling one. Retrying this value will fail identically."
)

_PROPOSAL_ON_AN_ACCEPT = (
    "outlook_respond_to_invite was given `proposed_new_time` with the response `accept`. "
    + "Microsoft takes a new time only with a decline or a tentative response. NO RESPONSE WAS "
    + "SENT. To propose a new time, use `decline` or `tentative`. To accept the time of the "
    + "organizer, remove `proposed_new_time`. If you call this tool again with the same "
    + "arguments, the call will fail the same way."
)

_PROPOSAL_WITH_NO_RESPONSE = (
    "outlook_respond_to_invite was given `proposed_new_time` with `send_response` false. "
    + "Microsoft sends a new time to the organizer only in a response, so a proposal needs "
    + "`send_response` true. NO RESPONSE WAS SENT. To propose a new time, set `send_response` to "
    + "true. If you call this tool again with the same arguments, the call will fail the same "
    + "way."
)

_BACKWARD_PROPOSAL = (
    "outlook_respond_to_invite was given a `proposed_new_time` with an `ends_at` that is not "
    + "after its `starts_at`. Both are wall-clock times in its `time_zone`. NO RESPONSE WAS SENT. "
    + "Work out the end from the start and call again."
)


def _bad_moment(argument: str, value: str) -> str:
    return (
        f"outlook_respond_to_invite was given {value!r} in `proposed_new_time.{argument}`, which "
        + "is not a local wall-clock time. Write it as `YYYY-MM-DDTHH:MM` or "
        + "`YYYY-MM-DDTHH:MM:SS`, with no offset and no `Z`. The zone goes in "
        + "`proposed_new_time.time_zone` alone. NO RESPONSE WAS SENT. If you call this tool again "
        + "with the same arguments, the call will fail the same way."
    )


def _proposals_off(event: Event) -> str:
    address = _organizer_address(event)
    who = "The organizer" if address is None else f"The organizer, {address},"
    return (
        f"{who} does not allow new time proposals for {_name(event)!r}, so Microsoft refuses "
        + "a proposal for it. NO RESPONSE WAS SENT. To respond with no new time, remove "
        + "`proposed_new_time`. If you call this tool again with the same arguments, the call "
        + "will fail the same way."
    )


class ProposedTime(BaseModel):
    starts_at: str = Field(
        min_length=1,
        description=(
            "The start of the new time, as a local wall-clock time in `time_zone`: "
            + "`YYYY-MM-DDTHH:MM` or `YYYY-MM-DDTHH:MM:SS`, for example `2026-03-02T14:00`. This "
            + "value must carry no offset and no `Z`."
        ),
    )
    ends_at: str = Field(
        min_length=1,
        description=(
            "The end of the new time, in the same form and zone as `starts_at`, and after it. A "
            + "meeting that runs past midnight ends on the next day."
        ),
    )
    time_zone: str = Field(
        min_length=1,
        pattern=ZONE_NAME,
        description=(
            "The zone that `starts_at` and `ends_at` use. This tool reads an IANA name, such as "
            + "`Europe/Berlin`, a Windows name, such as `W. Europe Standard Time`, and `UTC`. Ask "
            + "the user for the zone, because a wrong zone proposes a time that is hours off."
        ),
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
    proposed_new_time: ProposedTime | None = Field(
        description=(
            "The new time that this call proposed to the organizer, from the arguments. "
            + "Microsoft answers a response with no body, so this tool cannot read it back. This "
            + "field is null when the call proposed no time."
        )
    )


async def respond_to_invite(
    client: GraphServiceClient,
    *,
    uri: str,
    response: Response,
    comment: str | None = None,
    send_response: bool = True,
    proposed_new_time: ProposedTime | None = None,
    confirm: Confirm,
) -> InvitationResponse | InputRequiredResult:
    handle = event_handle(uri)
    if handle is None:
        raise ToolError(_NOT_A_HANDLE)
    if proposed_new_time is not None:
        _proposable(proposed_new_time, response=response, send_response=send_response)

    asked: InputRequiredResult | None = None
    proposed = (
        ()
        if proposed_new_time is None
        else (proposed_new_time.starts_at, proposed_new_time.ends_at, proposed_new_time.time_zone)
    )
    about = confirmation_id_for(handle.uri, response, repr(comment), repr(send_response), *proposed)
    with graph_errors(TOOL_NAME):
        event = await event_of(
            client,
            calendar_id=handle.calendar_id,
            event_id=handle.event_id,
            also=_PROPOSAL_FIELDS,
        )
        refused = (
            _proposals_off(event)
            if proposed_new_time is not None and event.allow_new_time_proposals is False
            else None
        )
        if refused is None and send_response:
            with not_graph():
                answer = await confirm(
                    _question(event, response, comment, proposed_new_time), about
                )
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
                    proposed_new_time=_slot(proposed_new_time),
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return _answer(
        handle,
        event,
        response,
        comment=comment,
        send_response=send_response,
        proposed_new_time=proposed_new_time,
    )


def _proposable(proposal: ProposedTime, *, response: Response, send_response: bool) -> None:
    if response == "accept":
        raise ToolError(_PROPOSAL_ON_AN_ACCEPT)
    if not send_response:
        raise ToolError(_PROPOSAL_WITH_NO_RESPONSE)
    opens = _moment("starts_at", proposal.starts_at)
    closes = _moment("ends_at", proposal.ends_at)
    if closes <= opens:
        raise ToolError(_BACKWARD_PROPOSAL)


def _moment(argument: str, value: str) -> datetime:
    moment = wall_clock(value)
    if moment is None:
        raise ToolError(_bad_moment(argument, value))
    return moment


def _slot(proposal: ProposedTime | None) -> TimeSlot | None:
    if proposal is None:
        return None
    return TimeSlot(
        start=DateTimeTimeZone(date_time=proposal.starts_at, time_zone=proposal.time_zone),
        end=DateTimeTimeZone(date_time=proposal.ends_at, time_zone=proposal.time_zone),
    )


async def _sent(
    client: GraphServiceClient,
    handle: EventHandle,
    response: Response,
    *,
    comment: str | None,
    send_response: bool,
    proposed_new_time: TimeSlot | None,
) -> None:
    events = client.me.calendars.by_calendar_id(handle.calendar_id).events.by_event_id(
        handle.event_id
    )
    configuration = RequestConfiguration[QueryParameters](options=no_retry())
    if response == "accept":
        assert proposed_new_time is None, "an accept carries no new time past _proposable"
        await events.accept.post(
            AcceptPostRequestBody(comment=comment, send_response=send_response),
            request_configuration=configuration,
        )
    elif response == "decline":
        await events.decline.post(
            DeclinePostRequestBody(
                comment=comment,
                send_response=send_response,
                proposed_new_time=proposed_new_time,
            ),
            request_configuration=configuration,
        )
    else:
        await events.tentatively_accept.post(
            TentativelyAcceptPostRequestBody(
                comment=comment,
                send_response=send_response,
                proposed_new_time=proposed_new_time,
            ),
            request_configuration=configuration,
        )


def _name(event: Event) -> str:
    return event.subject or "this event"


def _organizer_address(event: Event) -> str | None:
    organizer = event.organizer
    return organizer.email_address.address if organizer and organizer.email_address else None


def _question(
    event: Event, response: Response, comment: str | None, proposal: ProposedTime | None
) -> str:
    to = _organizer_address(event) or "the organizer"
    said = f" ({comment!r})" if comment else ""
    proposed = (
        ""
        if proposal is None
        else f" and propose the new time from {proposal.starts_at} to {proposal.ends_at} "
        + f"{proposal.time_zone}"
    )
    return (
        f"{_VERB[response]} {_name(event)!r}{proposed}? Microsoft mails{said} {to}, and this "
        + "connector cannot recall it."
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
    proposed_new_time: ProposedTime | None,
) -> InvitationResponse:
    return InvitationResponse(
        uri=handle.uri,
        subject=event.subject,
        organizer=MailAddress.from_recipient(event.organizer),
        response=_RECORDED_AS[response],
        comment=comment,
        sent_response=send_response,
        proposed_new_time=proposed_new_time,
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
        proposed_new_time: Annotated[
            ProposedTime | None,
            Field(
                description=(
                    "A new time to propose to the organizer, with a `decline` or a `tentative` "
                    + "response only. Microsoft takes a proposal only when `send_response` is "
                    + "true and the organizer allows new time proposals. outlook_read_event "
                    + "reports the choice of the organizer in `allow_new_time_proposals`. Omit "
                    + "this parameter to propose no time."
                )
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> InvitationResponse | InputRequiredResult:
        return await respond_to_invite(
            client,
            uri=uri,
            response=response,
            comment=comment,
            send_response=send_response,
            proposed_new_time=proposed_new_time,
            confirm=a_person_agrees(ctx),
        )
