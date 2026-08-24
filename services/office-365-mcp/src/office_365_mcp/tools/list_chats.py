"""`list_chats` — the signed-in user's Teams chats, most recent first.

TRAP: Graph's `lastUpdatedDateTime` changes on a rename or a member change and is not recency. Only
the last message sent decides `last_message_at` and the sort order, which needs `Chat.Read` rather
than `Chat.ReadBasic`.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.generated.models.chat import Chat
from msgraph.generated.models.conversation_member import ConversationMember
from msgraph.generated.users.item.chats.chats_request_builder import ChatsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors
from office_365_mcp.shared.handles import CHAT_PERMISSION, meeting_uri_for
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "list_chats"

STEP = "chats"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

MAX_CHATS = 50

MEMBERS_PER_CHAT = 25

_RECENCY = "lastMessagePreview/createdDateTime desc"

type _ChatsQuery = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
List the signed-in user's Teams chats — one-to-one, group and meeting — ordered by last message \
sent. Call it to see who is in a conversation, when it was last active, or for a meeting's \
`meeting_uri`, the only route to its transcripts and recordings — no filter exists, so match it by \
subject in `topic`. Channel activity is listed nowhere here: browse_channel walks one, \
search_messages finds a message. Returns id, type, topic, last-message time and members for \
unnamed chats.\
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

    @classmethod
    def from_conversation_member(cls, member: ConversationMember, *, include_email: bool) -> Self:
        return cls(
            display_name=member.display_name,
            email=member.email
            if include_email and isinstance(member, AadUserConversationMember)
            else None,
        )


class ChatSummary(BaseModel):
    chat_id: str = Field(
        description=(
            "Graph id for this chat (e.g. `19:...@thread.v2`). Microsoft puts this on every "
            + "message in the chat. Not a `teams:///` handle and cannot be assembled into one. "
            + "read_message takes only a handle a tool result carries."
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
            + "to meeting. Pass it verbatim to list_meeting_transcripts to find out whether the "
            + "meeting was transcribed. Null when no join URL exists, in which case that meeting's "
            + "transcripts are unreachable from this connector."
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
            + "decisions about chat membership. Match a member by display name, or by email with "
            + "`include_member_emails`; this list carries no user ids, so nothing in it can be "
            + "compared with get_me's `user_id`."
        )
    )
    members_may_be_incomplete: bool = Field(
        description=(
            f"True when `members` reached Graph's cap of {MEMBERS_PER_CHAT} per chat. A chat with "
            + f"exactly {MEMBERS_PER_CHAT} members is indistinguishable from one with more. Always "
            + "false when `members` is null."
        )
    )

    @classmethod
    def from_chat(cls, chat: Chat, *, include_member_emails: bool) -> Self:
        assert chat.id is not None, "Graph returned a chat with no id"
        preview = chat.last_message_preview
        # Graph documents `topic` as absent when unnamed; a blank one survives the SDK as `""`.
        topic = chat.topic if chat.topic is not None and chat.topic.strip() else None
        members = _members(chat, include_member_emails) if topic is None else None
        # Not `.value`: `ChatType` subclasses `str`, so the member is its wire value already, and
        # `.value` is typed as a one-tuple (the generated members carry a trailing comma).
        meeting = chat.online_meeting_info
        return cls(
            chat_id=chat.id,
            chat_type=chat.chat_type if chat.chat_type is not None else "unknown",
            topic=topic,
            meeting_uri=meeting_uri_for(meeting.join_web_url) if meeting is not None else None,
            last_message_at=preview.created_date_time if preview is not None else None,
            created_at=chat.created_date_time,
            members=members,
            members_may_be_incomplete=members is not None and len(members) >= MEMBERS_PER_CHAT,
        )


class ChatList(BaseModel):
    chats: list[ChatSummary] = Field(
        description=(
            "The user's chats, most recent first. A full window may have more. A short one is "
            + f"all. Raise `limit` (up to {MAX_CHATS}) to see further back. The notes-to-self "
            + "chat is usually the oneOnOne chat whose only member is the user — call get_me to "
            + "confirm."
        )
    )


async def list_recent_chats(
    client: GraphServiceClient, *, limit: int, include_member_emails: bool
) -> ChatList:
    assert 1 <= limit <= MAX_CHATS, f"limit must be within 1..{MAX_CHATS}, got {limit}"

    configuration = RequestConfiguration[_ChatsQuery](
        query_parameters=ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters(
            # Graph rejects `$select` on this collection; these expansions bring the fields back.
            expand=["members", "lastMessagePreview"],
            orderby=[_RECENCY],
            top=limit,
        )
    )
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.me.chats.get(request_configuration=configuration)
        assert first_page is not None, "Graph answered GET /me/chats with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return ChatList(
        chats=[
            ChatSummary.from_chat(chat, include_member_emails=include_member_emails)
            for chat in collected.items
        ]
    )


def _members(chat: Chat, include_emails: bool) -> list[ChatMember]:
    return [
        ChatMember.from_conversation_member(member, include_email=include_emails)
        for member in chat.members or []
    ]


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    # Closes over `transport` here; the default below holds this name, not a call (ruff's B008).
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
