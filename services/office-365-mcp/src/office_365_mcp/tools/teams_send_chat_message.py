import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

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

TOOL_NAME = "teams_send_chat_message"

STEP_SEND = "send_chat_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChatMessage.Send",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_list_chat_messages",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "chat_id": "19:release@thread.v2",
    "message": "Ship it.",
}

type ChatImportance = Literal["normal", "high", "urgent"]

_AGREE = "send"
_DECLINE = "do not send"
_NOTHING_SENT = "Nothing was sent."
_CANNOT_BE_RECALLED = "This cannot be recalled once sent."

_DESCRIPTION = """\
Sends one message as the signed-in user to an existing Teams chat. The message can @mention \
people. The mentions come first, in the order given, and the text of `message` follows them. \
This tool sends the message immediately, and nothing here can recall it. \
teams_send_channel_message is the tool for a channel.

Notes:
- This tool asks the user to agree before it sends anything, every time. This tool sends \
nothing unless the user agrees.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
teams_list_chat_messages does not already show the message.
"""


async def send_chat_message(
    client: GraphServiceClient,
    *,
    chat_id: str,
    message: str,
    confirm: Confirm,
    mentions: Sequence[Mention] = (),
    importance: ChatImportance | None = None,
) -> TeamsMessage | InputRequiredResult:
    question = _question(message, chat_id, mentions, importance=importance)
    about = _about(message, chat_id, mentions, importance=importance)
    sent: ChatMessage | None = None
    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME, step=STEP_SEND):
        with not_graph():
            answer = await confirm(question, about)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            sent = await client.chats.by_chat_id(chat_id).messages.post(
                outgoing_message(
                    message,
                    mentions=mentions,
                    importance=None if importance is None else ChatMessageImportance(importance),
                ),
                request_configuration=_send_request(),
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert sent is not None, "a send that nothing refused answered with no message"
    assert sent.id is not None, "Graph accepted a chat message post but returned no id"
    return TeamsMessage.from_message(sent, handle=MessageHandle(sent.id, chat_id=chat_id))


def _question(
    message: str, chat_id: str, mentions: Sequence[Mention], *, importance: ChatImportance | None
) -> str:
    named = ", ".join(repr(cut_for_a_question(mention.name)) for mention in mentions)
    mentioned = f" It mentions {named}." if mentions else ""
    marked = "" if importance is None else f" with {importance} importance"
    return (
        f"Send {cut_for_a_question(message)!r}{marked} to chat {chat_id!r} now?{mentioned} "
        + _CANNOT_BE_RECALLED
    )


def _about(
    message: str, chat_id: str, mentions: Sequence[Mention], *, importance: ChatImportance | None
) -> str:
    mentioned = [[mention.user_id, mention.name] for mention in mentions]
    return hashlib.sha256(
        json.dumps([chat_id, message, mentioned, importance]).encode()
    ).hexdigest()


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
        mentions: Annotated[
            list[Mention],
            Field(
                default=[],
                description=(
                    "The people to @mention, one entry for each person. This tool writes the "
                    + "mention markup itself, so `message` stays plain text. An empty list sends "
                    + "a message with no mention."
                ),
            ),
        ],
        ctx: Context,
        importance: Annotated[
            ChatImportance | None,
            Field(
                description=(
                    "The importance of the new message: `normal`, `high`, or `urgent`. Set this "
                    + "parameter only when the user asks for an importance."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage | InputRequiredResult:
        return await send_chat_message(
            client,
            chat_id=chat_id,
            message=message,
            confirm=a_person_agrees(ctx),
            mentions=mentions,
            importance=importance,
        )
