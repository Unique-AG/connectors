from collections.abc import Mapping, Sequence
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.chat_message_importance import ChatMessageImportance
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_step, no_retry
from office_365_mcp.shared.body_html import TEAMS_BODY_HTML_FIELD
from office_365_mcp.shared.citations import ACTION_NOT_A_SOURCE
from office_365_mcp.shared.handles import MessageHandle
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)
from office_365_mcp.shared.teams.messages import (
    CHANNEL_ID_FIELD,
    CHANNEL_IMPORTANCE_FIELD,
    CHANNEL_POST,
    CHANNEL_SUBJECT_FIELD,
    MENTIONS_FIELD,
    REPLY_TO_ID_FIELD,
    TEAM_ID_FIELD,
    ChannelImportance,
    Mention,
    TeamsMessage,
    outgoing_message,
    post_once_agreed,
    send_binding,
    send_question,
    subject_on_a_reply,
)

TOOL_NAME = "teams_send_channel_message"

PRESETS: tuple[str, ...] = ("teams-write", "teams-write-files", "teams-edit")

STEP_SEND = "send_channel_message"
STEP_REPLY = "reply_channel_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChannelMessage.Send",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_browse_channel",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "channel_id": "19:general@thread.tacv2",
    "body_html": "<p>Ship it.</p>",
}

_DESCRIPTION = f"""\
Posts one new message as the signed-in user to an existing channel of a Teams team. With \
`reply_to_id`, this tool replies in the thread of an existing post. The message can @mention \
people. The mentions come first, in the order given, and the HTML of `body_html` follows them. \
This tool posts the message immediately, and nothing here can recall it. \
teams_send_chat_message is the tool for a chat.

Notes:
- This tool asks the user to agree before it posts anything, every time. This tool posts \
nothing unless the user agrees.
- The question shows the Microsoft Entra object id of each person in `mentions`. The `name` in the \
question is only a label. The message shows the same label.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
the channel does not already show the message.
- {ACTION_NOT_A_SOURCE}
"""


async def send_channel_message(
    client: GraphServiceClient,
    *,
    team_id: str,
    channel_id: str,
    body_html: str,
    confirm: Confirm,
    mentions: Sequence[Mention] = (),
    subject: str | None = None,
    importance: ChannelImportance | None = None,
    reply_to_id: str | None = None,
) -> TeamsMessage | InputRequiredResult:
    if subject is not None and reply_to_id is not None:
        raise ToolError(subject_on_a_reply(TOOL_NAME))
    where = "to" if reply_to_id is None else f"as a reply to post {reply_to_id!r} in"
    question = send_question(
        CHANNEL_POST,
        body_html,
        f"{where} channel {channel_id!r} in team {team_id!r}",
        mentions,
        subject=subject,
        importance=importance,
    )
    about = send_binding(
        (team_id, channel_id, repr(reply_to_id)),
        body_html,
        mentions,
        subject=subject,
        importance=importance,
    )

    async def post() -> ChatMessage | None:
        outgoing = outgoing_message(
            body_html,
            mentions=mentions,
            importance=None if importance is None else ChatMessageImportance(importance),
            subject=subject,
        )
        messages = client.teams.by_team_id(team_id).channels.by_channel_id(channel_id).messages
        configuration = RequestConfiguration[QueryParameters](options=no_retry())
        measured = graph_step(STEP_SEND) if reply_to_id is None else graph_step(STEP_REPLY)
        with measured:
            return await (
                messages.post(outgoing, request_configuration=configuration)
                if reply_to_id is None
                else messages.by_chat_message_id(reply_to_id).replies.post(
                    outgoing, request_configuration=configuration
                )
            )

    outcome = await post_once_agreed(confirm, question, about, post)

    if isinstance(outcome, InputRequiredResult):
        return outcome
    if isinstance(outcome, str):
        raise ToolError(outcome)
    assert outcome is not None, "a post that nothing refused answered with no message"
    assert outcome.id is not None, "Graph accepted a channel message post but returned no id"
    return TeamsMessage.from_message(
        outcome,
        handle=MessageHandle(
            outcome.id, team_id=team_id, channel_id=channel_id, reply_to_id=reply_to_id
        ),
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx,
        agree=CHANNEL_POST.agree,
        decline=CHANNEL_POST.decline,
        nothing_happened=CHANNEL_POST.nothing_sent,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Teams: Send a Channel Message",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def teams_send_channel_message(
        team_id: Annotated[str, Field(min_length=1, description=TEAM_ID_FIELD)],
        channel_id: Annotated[str, Field(min_length=1, description=CHANNEL_ID_FIELD)],
        body_html: Annotated[str, Field(min_length=1, description=TEAMS_BODY_HTML_FIELD)],
        mentions: Annotated[list[Mention], Field(default=[], description=MENTIONS_FIELD)],
        ctx: Context,
        subject: Annotated[
            str | None, Field(min_length=1, description=CHANNEL_SUBJECT_FIELD)
        ] = None,
        importance: Annotated[
            ChannelImportance | None, Field(description=CHANNEL_IMPORTANCE_FIELD)
        ] = None,
        reply_to_id: Annotated[
            str | None, Field(min_length=1, description=REPLY_TO_ID_FIELD)
        ] = None,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage | InputRequiredResult:
        return await send_channel_message(
            client,
            team_id=team_id,
            channel_id=channel_id,
            body_html=body_html,
            confirm=a_person_agrees(ctx),
            mentions=mentions,
            subject=subject,
            importance=importance,
            reply_to_id=reply_to_id,
        )
