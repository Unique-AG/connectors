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

TOOL_NAME = "teams_send_chat_message"

STEP_SEND = "send_chat_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChatMessage.Send",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "chat_id": "19:release@thread.v2",
    "message": "Ship it.",
}

_AGREE = "send"
_DECLINE = "do not send"
_NOTHING_SENT = "Nothing was sent."
_CANNOT_BE_RECALLED = "This cannot be recalled once sent."

_DESCRIPTION = "Posts one plain-text message to an existing Teams chat, after the user approves it."


async def send_chat_message(
    client: GraphServiceClient, *, chat_id: str, message: str, confirm: Confirm
) -> TeamsMessage | InputRequiredResult:
    question = _question(message, chat_id)
    sent: ChatMessage | None = None
    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME, step=STEP_SEND):
        with not_graph():
            answer = await confirm(question, question)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            sent = await client.chats.by_chat_id(chat_id).messages.post(
                _posted(message), request_configuration=_send_request()
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert sent is not None, "a send that nothing refused answered with no message"
    assert sent.id is not None, "Graph accepted a chat message post but returned no id"
    return TeamsMessage.from_message(sent, handle=MessageHandle(sent.id, chat_id=chat_id))


def _question(message: str, chat_id: str) -> str:
    return f"Send {cut_for_a_question(message)!r} to chat {chat_id!r} now? {_CANNOT_BE_RECALLED}"


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
        title="Send a Teams Chat Message",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def teams_send_chat_message(
        chat_id: Annotated[
            str,
            Field(
                min_length=1,
                description="The chat to post to, as reported by teams_list_chats.",
            ),
        ],
        message: Annotated[
            str,
            Field(min_length=1, description="The message to send, as plain text."),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage | InputRequiredResult:
        return await send_chat_message(
            client, chat_id=chat_id, message=message, confirm=a_person_agrees(ctx)
        )
