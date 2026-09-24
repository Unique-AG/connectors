import hashlib
from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.item_body import ItemBody
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, no_retry, not_graph
from office_365_mcp.shared.handles import MessageHandle
from office_365_mcp.shared.messages import TeamsMessage
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

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "channel_id": "19:general@thread.tacv2",
    "message": "Ship it.",
}

_AGREE = "post"
_DECLINE = "do not post"
_NOTHING_SENT = "Nothing was posted."
_CANNOT_BE_RECALLED = "This cannot be recalled once posted."

_DESCRIPTION = (
    "Posts one plain-text message to an existing Teams channel, after the user approves it."
)


async def send_channel_message(
    client: GraphServiceClient, *, team_id: str, channel_id: str, message: str, confirm: Confirm
) -> TeamsMessage | InputRequiredResult:
    question = _question(message, team_id, channel_id)
    about = _about(message, team_id, channel_id)
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
                .messages.post(_posted(message), request_configuration=_send_request())
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


def _question(message: str, team_id: str, channel_id: str) -> str:
    return (
        f"Post {cut_for_a_question(message)!r} to channel {channel_id!r} in team {team_id!r} "
        f"now? {_CANNOT_BE_RECALLED}"
    )


def _about(message: str, team_id: str, channel_id: str) -> str:
    return f"{team_id}:{channel_id}:{hashlib.sha256(message.encode()).hexdigest()}"


def _posted(message: str) -> ChatMessage:
    return ChatMessage(body=ItemBody(content=message, content_type=BodyType.Text))


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
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage | InputRequiredResult:
        return await send_channel_message(
            client,
            team_id=team_id,
            channel_id=channel_id,
            message=message,
            confirm=a_person_agrees(ctx),
        )
