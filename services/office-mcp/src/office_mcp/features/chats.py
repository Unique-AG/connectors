"""The signed-in user's Microsoft Teams chats, most recently active first.

Three Graph facts shape everything here, all from the list-chats reference
(https://learn.microsoft.com/en-us/graph/api/chat-list):

* `lastMessagePreview/createdDateTime desc` is the **only** ordering Graph will apply to this
  collection, and it is the one that means "recently active". The chat's own
  `lastUpdatedDateTime` looks like activity and is not: Graph documents it as when the chat was
  renamed or its membership last changed. `services/teams-mcp` reached the same conclusion the
  hard way ("order list_chats by recency").
* `$top` may be at most 50, and Graph warns that a page can come back short of `$top` with an
  `@odata.nextLink` still set — so filling a window needs the page walk `collect_pages` does, and
  a short first page is not evidence that there are no more chats.
* `$expand=members` returns at most 25 members per chat "even if a larger `$top` value is
  specified". That truncation is silent, which is exactly how a model comes to summarise a
  200-person chat from 25 names, so it is reported as a field.
"""

from datetime import datetime

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.generated.models.chat import Chat
from msgraph.generated.users.item.chats.chats_request_builder import ChatsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import collect_pages, graph_errors

# Reading a chat's `lastMessagePreview` is reading a message, which `Chat.ReadBasic` — "read the
# names and members of chats" — does not cover; `Chat.Read` is the least privilege that does.
GRAPH_PERMISSION = "Chat.Read"

# Graph's documented `$top` ceiling on this collection. The tool's schema derives its `limit`
# maximum from this, so the bound a caller sees is the bound Graph actually enforces.
MAX_CHATS = 50

# Graph's documented cap on `$expand=members`, per chat.
MEMBERS_PER_CHAT = 25

_RECENCY = "lastMessagePreview/createdDateTime desc"

type _ChatsQuery = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters


class ChatMember(BaseModel):
    display_name: str | None = Field(
        description="The member's name as Teams shows it. Null for some external participants."
    )
    email: str | None = Field(
        default=None,
        description=(
            "The member's email address, present only when `include_member_emails` was set. Null "
            + "for a participant Graph has no address for, such as a room or a phone dial-in."
        ),
    )


class ChatSummary(BaseModel):
    chat_id: str = Field(
        description=(
            "The chat's Graph id, e.g. `19:...@thread.v2`. Pass it verbatim to any tool that "
            + "takes a chat id; it cannot be reconstructed from a topic or a member's name."
        )
    )
    chat_type: str = Field(
        description=(
            "`oneOnOne`, `group` or `meeting` — a meeting chat is the conversation attached to a "
            + "Teams meeting. `unknown` if Graph reported a type this connector predates."
        )
    )
    topic: str | None = Field(
        description=(
            "The chat's name. Null for every oneOnOne chat and for group chats nobody named — "
            + "those are identified by `members` instead."
        )
    )
    last_message_at: datetime | None = Field(
        description=(
            "When the last message in this chat was sent. This is the value the list is ordered "
            + "by, and the only 'recent activity' Microsoft Graph exposes for a chat. Null when "
            + "nobody has posted in the chat yet."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When the chat was created (Graph `createdDateTime`) — useful to tell apart chats "
            + "that share a topic."
        )
    )
    members: list[ChatMember] | None = Field(
        description=(
            "Who is in the chat. Returned only for chats with no `topic`, where the people are "
            + "the only way to name the chat; null otherwise, which is not a claim that the chat "
            + "has no members."
        )
    )
    members_truncated: bool = Field(
        description=(
            f"True when `members` hit Microsoft Graph's cap of {MEMBERS_PER_CHAT} members per "
            + "chat on this endpoint, so people are missing from the list. Always false when "
            + "`members` is null."
        )
    )


class ChatList(BaseModel):
    chats: list[ChatSummary] = Field(
        description="The signed-in user's chats, most recently active first."
    )
    truncated: bool = Field(
        description=(
            "True when the user has more chats than the `limit` returned here. There is no "
            + f"cursor: raise `limit` (up to {MAX_CHATS}) to widen the window. Chats less recent "
            + "than the window are not reachable from this tool."
        )
    )


async def list_recent_chats(
    client: GraphServiceClient, *, limit: int, include_member_emails: bool
) -> ChatList:
    """The `limit` most recently active chats, and whether the user has more than that."""
    assert 1 <= limit <= MAX_CHATS, f"limit must be within 1..{MAX_CHATS}, got {limit}"

    configuration = RequestConfiguration[_ChatsQuery](
        query_parameters=ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters(
            # `$select` is rejected on this collection as an unsupported parameter, so the
            # expansions are what bring back the fields below.
            expand=["members", "lastMessagePreview"],
            orderby=[_RECENCY],
            top=limit,
        )
    )
    with graph_errors():
        first_page = await client.me.chats.get(request_configuration=configuration)
        assert first_page is not None, "Graph answered GET /me/chats with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return ChatList(
        chats=[_summarise(chat, include_member_emails) for chat in collected.items],
        truncated=collected.truncated,
    )


def _summarise(chat: Chat, include_member_emails: bool) -> ChatSummary:
    assert chat.id is not None, "Graph returned a chat with no id"
    preview = chat.last_message_preview
    members = _members(chat, include_member_emails) if chat.topic is None else None
    # `ChatType` subclasses `str`, so the member *is* its wire value ("group") and pydantic
    # narrows it to a plain `str` on the way in. Its `.value` would be the obvious thing to reach
    # for and is typed as a one-tuple, because the generated members carry trailing commas
    # (`OneOnOne = "oneOnOne",`).
    return ChatSummary(
        chat_id=chat.id,
        chat_type=chat.chat_type if chat.chat_type is not None else "unknown",
        topic=chat.topic,
        last_message_at=preview.created_date_time if preview is not None else None,
        created_at=chat.created_date_time,
        members=members,
        members_truncated=members is not None and len(members) >= MEMBERS_PER_CHAT,
    )


def _members(chat: Chat, include_emails: bool) -> list[ChatMember]:
    """The chat's expanded members.

    Only `aadUserConversationMember` carries an email; a room, a phone participant or an
    anonymous meeting guest is a different subtype with a display name and nothing to match on.
    """
    return [
        ChatMember(
            display_name=member.display_name,
            email=member.email
            if include_emails and isinstance(member, AadUserConversationMember)
            else None,
        )
        for member in chat.members or []
    ]
