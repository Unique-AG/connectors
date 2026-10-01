import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, no_retry, not_graph
from office_365_mcp.shared.handles import MessageHandle
from office_365_mcp.shared.messages import Mention, TeamsMessage, outgoing_message
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_send_channel_message"

STEP_SEND = "send_channel_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChannelMessage.Send",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_browse_channel",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "channel_id": "19:general@thread.tacv2",
    "message": "Ship it.",
}

_AGREE = "post"
_DECLINE = "do not post"
_NOTHING_SENT = "Nothing was posted."
_CANNOT_BE_RECALLED = "This cannot be recalled once posted."

_DESCRIPTION = """\
Posts one new message as the signed-in user to an existing channel of a Teams team. The message \
can @mention people. The mentions come first, in the order given, and the text of `message` \
follows them. This tool posts the message immediately, and nothing here can recall it. \
teams_send_chat_message is the tool for a chat.

Notes:
- This tool asks the user to agree before it posts anything, every time. This tool posts \
nothing unless the user agrees.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
teams_browse_channel does not already show the message.
"""


async def send_channel_message(
    client: GraphServiceClient,
    *,
    team_id: str,
    channel_id: str,
    message: str,
    confirm: Confirm,
    mentions: Sequence[Mention] = (),
) -> TeamsMessage | InputRequiredResult:
    question = _question(message, team_id, channel_id, mentions)
    about = _about(message, team_id, channel_id, mentions)
    sent: ChatMessage | None = None
    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME, step=STEP_SEND):
        with not_graph():
            answer = await confirm(question, about)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            sent = await (
                client.teams.by_team_id(team_id)
                .channels.by_channel_id(channel_id)
                .messages.post(
                    outgoing_message(message, mentions=mentions),
                    request_configuration=_send_request(),
                )
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert sent is not None, "a post that nothing refused answered with no message"
    assert sent.id is not None, "Graph accepted a channel message post but returned no id"
    return TeamsMessage.from_message(
        sent, handle=MessageHandle(sent.id, team_id=team_id, channel_id=channel_id)
    )


def _question(message: str, team_id: str, channel_id: str, mentions: Sequence[Mention]) -> str:
    named = ", ".join(repr(cut_for_a_question(mention.name)) for mention in mentions)
    mentioned = f" It mentions {named}." if mentions else ""
    return (
        f"Post {cut_for_a_question(message)!r} to channel {channel_id!r} in team {team_id!r} "
        + f"now?{mentioned} {_CANNOT_BE_RECALLED}"
    )


def _about(message: str, team_id: str, channel_id: str, mentions: Sequence[Mention]) -> str:
    mentioned = [[mention.user_id, mention.name] for mention in mentions]
    return hashlib.sha256(
        json.dumps([team_id, channel_id, message, mentioned]).encode()
    ).hexdigest()


def _send_request() -> RequestConfiguration[QueryParameters]:
    return RequestConfiguration[QueryParameters](options=no_retry())


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_SENT)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Send a Teams Channel Message",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def teams_send_channel_message(
        team_id: Annotated[
            str,
            Field(
                min_length=1,
                description="The team the channel is in, as reported by teams_list_my_teams.",
            ),
        ],
        channel_id: Annotated[
            str,
            Field(
                min_length=1,
                description="The channel to post to, as reported by teams_list_channels.",
            ),
        ],
        message: Annotated[
            str,
            Field(min_length=1, description="The message to send, as plain text."),
        ],
        mentions: Annotated[
            list[Mention],
            Field(
                default=[],
                description=(
                    "The people to @mention, one entry for each person. This tool writes the "
                    + "mention markup itself, so `message` stays plain text. An empty list posts "
                    + "a message with no mention."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage | InputRequiredResult:
        return await send_channel_message(
            client,
            team_id=team_id,
            channel_id=channel_id,
            message=message,
            confirm=a_person_agrees(ctx),
            mentions=mentions,
        )
