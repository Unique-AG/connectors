"""`list_chats` — the signed-in user's Teams chats, most recent first.

Lists one-to-one, group, and meeting chats with id, type, topic, last message time, and members
(for unnamed chats). No message text. This tool names conversations for other tools and shows which
chats are live and when last posted in.

`limit` is a window, not a cursor. A full window may have more. A short one is all. The walk
follows Graph's paging to completion rather than trusting a short page.

Meeting chats (conversation attached to a Teams meeting) have the meeting subject as `topic` and
carry `meeting_uri`, the only route from conversation to meeting. Chat.Read is required (not
Chat.ReadBasic) for recency sort.
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

from office_mcp.graph_client import collect_pages, graph_errors
from office_mcp.shared.handles import CHAT_PERMISSION, meeting_uri_for
from office_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "list_chats"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION,)

MAX_CHATS = 50

MEMBERS_PER_CHAT = 25

_RECENCY = "lastMessagePreview/createdDateTime desc"

type _ChatsQuery = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters

_DESCRIPTION = f"""\
List the signed-in user's Microsoft Teams chats: one-to-one, group, and meeting chats, most \
recent first. Returns id, type, topic, last-message time, and members (for unnamed chats).

Use this to see which conversations are live, who is in them, and when each was last posted. No \
message text is returned. Search_messages is the route to any. Chat_id here is what Microsoft \
puts on every message in that chat, so this list names messages found elsewhere. Not an argument \
to any tool. This returns chats only; channels live inside teams and are a different surface.

Meeting chats are conversations attached to a Teams meeting. The `topic` is the meeting subject. \
`meeting_uri` is the only route from conversation to meeting. No calendar permission needed. \
`meeting_uri` is null for non-meeting chats and for meeting chats where Microsoft gave no join URL.

Order comes from the last message sent in each chat — the only recency Graph applies. \
`last_message_at` is null if no one has posted yet. `members` returns only for unnamed chats \
(members are the name). Graph caps members at {MEMBERS_PER_CHAT} per chat with no total. \
`members_may_be_incomplete` says when the list reached that cap. Set `include_member_emails` \
when members share a display name.

`limit` is a window on the most recent chats. A full window means more may exist. A short one is \
all. Raise `limit` up to {MAX_CHATS} to see further back. The notes-to-self chat is usually the \
oneOnOne chat whose only member is the user—call get_me to confirm. Members match by display name \
or by email (with `include_member_emails`). This list carries no user ids.\
"""


class ChatMember(BaseModel):
    display_name: str | None = Field(
        description="The member's display name. Null for some external users."
    )
    email: str | None = Field(
        default=None,
        description=(
            "The member's email. Present only when `include_member_emails` is set. Null for rooms "
            + "or phone dial-ins."
        ),
    )


class ChatSummary(BaseModel):
    chat_id: str = Field(
        description=(
            "Graph id for this chat (e.g. `19:...@thread.v2`). Microsoft puts this on every "
            + "message in the chat. Do not try to assemble this into a message handle by itself; "
            + "the handle format requires both chat_id and message_id."
        )
    )
    chat_type: str = Field(
        description=(
            "`oneOnOne`, `group`, or `meeting`. Null becomes `unknown` if Graph reports a newer "
            + "type."
        )
    )
    topic: str | None = Field(
        description=(
            "Chat name. Null for oneOnOne chats and unnamed group chats (use `members` for those)."
        )
    )
    meeting_uri: str | None = Field(
        description=(
            "For meeting chats: a handle for the Teams meeting. The only route from conversation "
            + "to meeting. Null when no join URL exists."
        )
    )
    last_message_at: datetime | None = Field(
        description=(
            "When the last message was sent. Null if no one has posted. The sort order is by this "
            + "field."
        )
    )
    created_at: datetime | None = Field(
        description="When the chat was created. Distinguish chats with the same topic."
    )
    members: list[ChatMember] | None = Field(
        description=(
            "Who is in the chat. Returned only for unnamed chats (where members are the name). "
            + "Null otherwise. A null field does not mean the chat has no members; it means "
            + "members are not returned for named chats. Do not use this incomplete list to make "
            + "decisions about chat membership."
        )
    )
    members_may_be_incomplete: bool = Field(
        description=(
            f"True when `members` reached Graph's cap of {MEMBERS_PER_CHAT} per chat. A chat with "
            + f"exactly {MEMBERS_PER_CHAT} members is indistinguishable from one with more. Always "
            + "false when `members` is null."
        )
    )


class ChatList(BaseModel):
    chats: list[ChatSummary] = Field(
        description=(
            "The user's chats, most recent first. A full window may have more. A short one is "
            + f"all. Raise `limit` (up to {MAX_CHATS}) to see further back."
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
    with graph_errors(TOOL_NAME):
        first_page = await client.me.chats.get(request_configuration=configuration)
        assert first_page is not None, "Graph answered GET /me/chats with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return ChatList(chats=[_summarise(chat, include_member_emails) for chat in collected.items])


def _summarise(chat: Chat, include_member_emails: bool) -> ChatSummary:
    assert chat.id is not None, "Graph returned a chat with no id"
    preview = chat.last_message_preview
    # Graph documents `topic` as absent on an unnamed chat, but a blank one survives the SDK as `""`
    # and is not a name either. Normalised once, here, so a caller never has to tell the two apart.
    topic = chat.topic if chat.topic is not None and chat.topic.strip() else None
    members = _members(chat, include_member_emails) if topic is None else None
    # `chat_type` is passed as-is, not as `chat.chat_type.value`. `ChatType` subclasses `str`, so
    # the member already is its wire value ("group"). `.value` looks like the right way to read
    # it but is typed as a one-tuple, because the generated members carry a trailing comma
    # (`OneOnOne = "oneOnOne",`).
    meeting = chat.online_meeting_info
    return ChatSummary(
        chat_id=chat.id,
        chat_type=chat.chat_type if chat.chat_type is not None else "unknown",
        topic=topic,
        meeting_uri=meeting_uri_for(meeting.join_web_url) if meeting is not None else None,
        last_message_at=preview.created_date_time if preview is not None else None,
        created_at=chat.created_date_time,
        members=members,
        members_may_be_incomplete=members is not None and len(members) >= MEMBERS_PER_CHAT,
    )


def _members(chat: Chat, include_emails: bool) -> list[ChatMember]:
    """Chat members. Only aadUserConversationMember carries email."""
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
    # Built here because this is where `transport` is, and named rather than called in the default.
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

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
                    "How many chats to return, most recent first. Default 25, maximum "
                    + f"{MAX_CHATS}."
                ),
            ),
        ] = 25,
        include_member_emails: Annotated[
            bool,
            Field(
                description=(
                    "Include each member's email. Off by default. Needed when members share a "
                    + "display name."
                )
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> ChatList:
        return await list_recent_chats(
            client,
            limit=limit,
            include_member_emails=include_member_emails,
        )
