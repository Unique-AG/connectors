"""`list_chats` — signed-in user's Teams chats, most recent first.

Lists one-to-one, group, and meeting chats with id, type, topic, last message time, and members
(for unnamed chats). No message text returns. This tool names conversations for other tools and
shows which chats are live and when each was last posted in.

Three Graph constraints:

1. `lastMessagePreview/createdDateTime desc` is the only sort Graph applies. `lastUpdatedDateTime`
   (rename or member change) is not recency. Only `last_message_at` (from last message sent) is
   returned.

2. `$top` is at most 50. A short page with `@odata.nextLink` means more follows. Short pages do
   not mean the end.

3. `$expand=members` returns at most 25 per chat with no total. A full list at the cap is flagged
   as possibly incomplete.

`limit` is a window, not a cursor. A full window means more may exist. A short window means that
is all. No pagination flag: the walk follows Graph's paging to completion rather than trusting a
short page.

Meeting chats (conversation attached to Teams meeting) are in this list with the meeting subject
as `topic`. `onlineMeetingInfo` is in the default projection—no extra request or permission needed.
`meeting_uri` on each meeting chat is the only route from conversation to meeting. `Chat.Read` is
needed, not `Chat.ReadBasic`, because recency sort needs `lastMessagePreview`.
"""

from datetime import datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.generated.models.chat import Chat
from msgraph.generated.users.item.chats.chats_request_builder import ChatsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import collect_pages, graph_client_for, graph_errors
from office_mcp.shared.handles import CHAT_PERMISSION, meeting_uri_for
from office_mcp.shared.seam import READ_ONLY, graph_token, graph_tool_errors

TOOL_NAME = "list_chats"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION,)

_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

MAX_CHATS = 50

MEMBERS_PER_CHAT = 25

_RECENCY = "lastMessagePreview/createdDateTime desc"

type _ChatsQuery = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters

_DESCRIPTION = f"""\
List the signed-in user's Microsoft Teams chats: one-to-one, group, and meeting chats, most recent \
first. Returns each chat's id, type, topic, last-message time, and members (for unnamed chats).

Use this to see which conversations are live, who is in them, and when each was last posted in. Do \
not use for message content—no tool on this server reads messages. Also use to name a chat: \
`chat_id` is the id Microsoft puts on every message in that chat, so this is how to get a topic \
and participant list for a message found elsewhere. No tool takes a chat id as an argument. \
Returns chats only—Teams channels are inside teams and are a separate surface not listed here.

Meeting discovery: A `meeting` chat is the conversation attached to a Teams meeting. Its `topic` \
is the meeting subject and it carries `meeting_uri`—a handle for the meeting. There is no separate \
meeting tool because this list finds meetings by topic and recency. No calendar permission needed. \
No tool takes `meeting_uri` as an argument yet, so it identifies meetings rather than opening \
them. `meeting_uri` is null for non-meeting chats and for meeting chats where Microsoft returned \
no join URL—nothing else here addresses that meeting, so there is no other route to try.

Order and `last_message_at` come from the last message sent in the chat—the only recency order \
Graph applies. Graph's `lastUpdatedDateTime` (rename or member change) is not returned on purpose: \
a chat with no new messages for a year can carry today's timestamp. `last_message_at` is null if \
no one has posted yet.

`members` returns only for chats with no `topic` (unnamed chats use members as the name). Graph \
caps the list at {MEMBERS_PER_CHAT} members per chat with no total. `members_may_be_incomplete` \
says when the list reached that cap—members may be missing. Graph does not say whether they are. \
Set `include_member_emails` when two members share a display name.

No pagination and no cursor. `limit` is a window on the most recent chats. A full window means \
the user may have more. A short window means that is all—the walk follows Microsoft's paging to \
completion rather than trusting a short page. Raise `limit` up to {MAX_CHATS} (Graph's maximum \
for this collection) to see further back. The signed-in user's notes-to-self chat is usually the \
oneOnOne chat whose only member is them—call get_me to confirm who that is. Members match by \
display name or, with `include_member_emails` set, by email. This list carries no user ids.\
"""


class ChatMember(BaseModel):
    display_name: str | None = Field(
        description="The member's display name as Teams shows it. Null for some external users."
    )
    email: str | None = Field(
        default=None,
        description=(
            "The member's email. Present only when `include_member_emails` is set. Null for users "
            + "Graph has no address for—rooms or phone dial-ins."
        ),
    )


class ChatSummary(BaseModel):
    chat_id: str = Field(
        description=(
            "Graph id for this chat (e.g. `19:...@thread.v2`). Microsoft puts this id on every "
            + "message in this chat. Use this to identify which chat a message found elsewhere "
            + "came from. Not a tool argument. Not a `teams:///` handle and cannot be assembled "
            + "into one."
        )
    )
    chat_type: str = Field(
        description=(
            "`oneOnOne`, `group`, or `meeting`. A meeting chat is the conversation attached to a "
            + "Teams meeting. `unknown` if Graph reported a type this connector predates."
        )
    )
    topic: str | None = Field(
        description=(
            "Chat name. Null for oneOnOne chats and unnamed group chats. Those use `members` for "
            + "identification."
        )
    )
    meeting_uri: str | None = Field(
        description=(
            "For meeting chats: a handle for the Teams meeting behind this conversation. The only "
            + "route from conversation to meeting. No tool takes this as an argument yet. Null for "
            + "non-meeting chats and for meeting chats where Microsoft returned no join URL. When "
            + "null, nothing here addresses that meeting—there is no other route to try."
        )
    )
    last_message_at: datetime | None = Field(
        description=(
            "When the last message was sent in this chat. The sort order is by this field. The "
            + "only recency Microsoft Graph exposes for a chat. Null if no one has posted yet."
        )
    )
    created_at: datetime | None = Field(
        description="When the chat was created. Use to distinguish chats with the same topic."
    )
    members: list[ChatMember] | None = Field(
        description=(
            "Who is in the chat. Returned only for chats with no `topic`, where members are the "
            + "only name. Null otherwise—not a claim that the chat has no members."
        )
    )
    members_may_be_incomplete: bool = Field(
        description=(
            f"True when `members` reached Microsoft Graph's cap of {MEMBERS_PER_CHAT} per chat, so "
            + "the chat may have more members. Not proof that it does: a chat with exactly "
            + f"{MEMBERS_PER_CHAT} members is identical to one with 200. Do not use this list to "
            + "answer 'who is in this chat' when this is true. Always false when `members` is null."
        )
    )


class ChatList(BaseModel):
    chats: list[ChatSummary] = Field(
        description=(
            "The signed-in user's chats, most recent first. A full window means more may exist. A "
            + f"short window means that is all. No cursor: raise `limit` (up to {MAX_CHATS}) to "
            + "see further back."
        )
    )


async def list_recent_chats(
    client: GraphServiceClient, *, limit: int, include_member_emails: bool
) -> ChatList:
    """The `limit` most recently active chats."""
    assert 1 <= limit <= MAX_CHATS, f"limit must be within 1..{MAX_CHATS}, got {limit}"

    configuration = RequestConfiguration[_ChatsQuery](
        query_parameters=ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters(
            # Graph rejects `$select` on this collection as an unsupported parameter. These
            # expansions are what bring back the fields below instead.
            expand=["members", "lastMessagePreview"],
            orderby=[_RECENCY],
            top=limit,
        )
    )
    with graph_errors():
        first_page = await client.me.chats.get(request_configuration=configuration)
        assert first_page is not None, "Graph answered GET /me/chats with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return ChatList(chats=[_summarise(chat, include_member_emails) for chat in collected.items])


def _summarise(chat: Chat, include_member_emails: bool) -> ChatSummary:
    assert chat.id is not None, "Graph returned a chat with no id"
    preview = chat.last_message_preview
    members = _members(chat, include_member_emails) if chat.topic is None else None
    # `chat_type` is passed as-is, not as `chat.chat_type.value`. `ChatType` subclasses `str`, so
    # the member already is its wire value ("group"). `.value` looks like the right way to read
    # it but is typed as a one-tuple, because the generated members carry a trailing comma
    # (`OneOnOne = "oneOnOne",`).
    meeting = chat.online_meeting_info
    return ChatSummary(
        chat_id=chat.id,
        chat_type=chat.chat_type if chat.chat_type is not None else "unknown",
        topic=chat.topic,
        # Asked of the one module that spells this scheme, never assembled here: a null join URL is
        # an outcome that speller already knows, and a second speller is free to disagree with it.
        meeting_uri=meeting_uri_for(meeting.join_web_url) if meeting is not None else None,
        last_message_at=preview.created_date_time if preview is not None else None,
        created_at=chat.created_date_time,
        members=members,
        members_may_be_incomplete=members is not None and len(members) >= MEMBERS_PER_CHAT,
    )


def _members(chat: Chat, include_emails: bool) -> list[ChatMember]:
    """Chat members. Only `aadUserConversationMember` carries email."""
    return [
        ChatMember(
            display_name=member.display_name,
            email=member.email
            if include_emails and isinstance(member, AadUserConversationMember)
            else None,
        )
        for member in chat.members or []
    ]


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Register this tool against the shared Graph transport.

    `transport` is the long-lived client from `create_graph_transport`. This tool borrows it per
    call and does not own it; `create_app` closes it on shutdown.
    """

    @mcp.tool(
        name=TOOL_NAME,
        title="List My Teams Chats",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def list_chats(
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_CHATS,
                description=(
                    "How many chats to return, most recent first. Default 25. Microsoft Graph "
                    + "refuses larger pages on this collection."
                ),
            ),
        ] = 25,
        include_member_emails: Annotated[
            bool,
            Field(
                description=(
                    "Include each member's email. Off by default—only needed when two members "
                    + "share a display name."
                )
            ),
        ] = False,
        graph_token: str = _TOKEN,
    ) -> ChatList:
        with graph_tool_errors(*GRAPH_PERMISSIONS):
            return await list_recent_chats(
                graph_client_for(transport, graph_token),
                limit=limit,
                include_member_emails=include_member_emails,
            )
