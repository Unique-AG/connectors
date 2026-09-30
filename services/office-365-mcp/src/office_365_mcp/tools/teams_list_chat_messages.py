from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Annotated

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.chats.item.messages.messages_request_builder import MessagesRequestBuilder
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import CHAT_PERMISSION, MessageHandle
from office_365_mcp.shared.messages import TeamsMessage
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import closes_at, opens_at

TOOL_NAME = "teams_list_chat_messages"

STEP = "chat_messages"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"chat_id": "19:release@thread.v2"}

MAX_MESSAGES = 50

_NEWEST_FIRST = "createdDateTime desc"

_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

_MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the newest messages of one Teams chat of the signed-in user, newest first, by the `chat_id` \
that teams_list_chats reported. Each row is the full message, with a `uri` that teams_read_message \
accepts. teams_browse_channel is the sibling tool for a channel, and teams_search_messages finds a \
message by its text.

Notes:
- To read further back, pass the oldest `created_at` as `sent_before`. Messages from that same \
second come back again at the top of the list.
- One call is one request, because a given chat allows this whole connector about one request a \
second, across the whole tenant.\
"""


class ChatMessages(BaseModel):
    messages: list[TeamsMessage] = Field(
        description=(
            "The messages of the chat, newest first, in the order that Microsoft 365 sent them. "
            + "System events are rows too, and the `event` of each one says what happened."
        )
    )
    more_messages: bool = Field(
        description=(
            "True when Microsoft 365 holds messages older than the last row of this list. False "
            + "means that this list includes the first message of the chat."
        )
    )


async def list_chat_messages(
    client: GraphServiceClient,
    *,
    chat_id: str,
    limit: int,
    sent_before: date | datetime | None = None,
) -> ChatMessages:
    assert 1 <= limit <= MAX_MESSAGES, f"limit must be within 1..{MAX_MESSAGES}, got {limit}"

    configuration = RequestConfiguration[_MessagesQuery](
        query_parameters=_MessagesQuery(
            top=limit, orderby=[_NEWEST_FIRST], filter=_sent_before_filter(sent_before)
        ),
        headers=_headers(),
    )
    with graph_errors(TOOL_NAME, step=STEP):
        page = await client.chats.by_chat_id(chat_id).messages.get(
            request_configuration=configuration
        )
        assert page is not None, "Graph answered a chat message listing with no collection"

    return ChatMessages(
        messages=[_row(message, chat_id) for message in page.value or []],
        more_messages=bool(page.odata_next_link),
    )


def _sent_before_filter(sent_before: date | datetime | None) -> str | None:
    if sent_before is None:
        return None
    return f"createdDateTime lt {_first_instant_past(sent_before):%Y-%m-%dT%H:%M:%SZ}"


def _first_instant_past(bound: date | datetime) -> datetime:
    if isinstance(bound, datetime):
        return closes_at(bound).replace(microsecond=0) + timedelta(seconds=1)
    return opens_at(bound + timedelta(days=1))


def _headers() -> HeadersCollection:
    headers = HeadersCollection()
    headers.add(*_PREFER_UNKNOWN_ENUMS)
    return headers


def _row(message: ChatMessage, chat_id: str) -> TeamsMessage:
    assert message.id is not None, "Graph returned a chat message with no id"
    return TeamsMessage.from_message(message, handle=MessageHandle(message.id, chat_id=chat_id))


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Messages in a Teams Chat",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def teams_list_chat_messages(
        chat_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The chat to read, as the `chat_id` that teams_list_chats reported, for "
                    + "example `19:...@thread.v2`. It is not a `teams:///` handle."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_MESSAGES,
                description=(
                    f"How many messages to return, at most {MAX_MESSAGES}. A system event, such "
                    + "as a member who joined the chat, counts as one message."
                ),
            ),
        ] = 20,
        sent_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only messages sent at or before this point, inclusive. A date, "
                    + "`2026-03-04`, covers that whole UTC day. A moment, "
                    + "`2026-03-04T09:00:00Z`, covers the whole second it names, and a moment "
                    + "with no zone is read as UTC."
                )
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> ChatMessages:
        return await list_chat_messages(
            client, chat_id=chat_id, limit=limit, sent_before=sent_before
        )
