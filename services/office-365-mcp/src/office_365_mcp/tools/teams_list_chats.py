"""`teams_list_chats` — the signed-in user's Teams chats, most recent first.

TRAP: `lastUpdatedDateTime` changes on a rename or a member change and is not recency. Only the
last message sent decides `last_message_at` and the sort order, which needs `Chat.Read`.

`chat_type` and `topic_contains` narrow rows in process: Graph names no filterable property on this
collection and drops an unsupported `$filter` in silence
(https://learn.microsoft.com/en-us/graph/query-parameters). The walk stops on `limit` MATCHES
rather than `limit` rows, so `capped` is what tells a full window apart from the end of the list.
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.generated.models.chat import Chat
from msgraph.generated.models.chat_type import ChatType
from msgraph.generated.models.conversation_member import ConversationMember
from msgraph.generated.users.item.chats.chats_request_builder import ChatsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors
from office_365_mcp.shared.handles import CHAT_PERMISSION, meeting_uri_for
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_list_chats"

STEP = "chats"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

MAX_CHATS = 50

MEMBERS_PER_CHAT = 25

_RECENCY = "lastMessagePreview/createdDateTime desc"

type ChatKind = Literal["oneOnOne", "group", "meeting"]

type _ChatsQuery = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the signed-in user's Teams chats — one-to-one, group, and meeting — newest last-message \
first, for seeing who is in a conversation, when it was last active, or reaching a meeting's \
`meeting_uri` for its transcripts and recordings. It does not cover channel activity: \
teams_browse_channel walks one channel, and teams_search_messages searches message text across \
chats and channels.

Notes:
- To find a meeting's `meeting_uri`, set `chat_type="meeting"` and, if known, `topic_contains`; \
there is no direct filter on `meeting_uri` itself.
- `chat_type` and `topic_contains` filter chats already fetched, so the search runs until it \
collects `limit` matches rather than stopping after `limit` rows; check `capped` before concluding \
no such chat exists.\
"""


class ChatMember(BaseModel):
    display_name: str | None = Field(
        description="The member's display name. Null for some external users."
    )
    email: str | None = Field(
        default=None,
        description=(
            "The member's email, present only when `include_member_emails` is set. Null for "
            + "rooms and phone dial-ins."
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
            "Graph's id for this chat, for example `19:...@thread.v2`. Not a `teams:///` handle "
            + "and cannot be assembled into one — teams_read_message needs a `uri` a search or "
            + "browse result reported."
        )
    )
    chat_type: str = Field(
        description=(
            "One of `oneOnOne`, `group`, or `meeting`, or `unknown` for a type Graph added after "
            + "this connector."
        )
    )
    topic: str | None = Field(
        description=(
            "Chat name. Null for oneOnOne chats and unnamed group chats (use `members` for those)."
        )
    )
    meeting_uri: str | None = Field(
        description=(
            "A handle for the Teams meeting behind this chat, the only route from conversation to "
            + "meeting — pass it verbatim to teams_list_meeting_transcripts to check whether the "
            + "meeting was transcribed. Null when the chat carries no join URL, in which case that "
            + "meeting's transcripts are unreachable from this connector."
        )
    )
    last_message_at: datetime | None = Field(
        description=(
            "When the last message was sent. Null if no one posted yet. The sort order is by "
            + "this field."
        )
    )
    created_at: datetime | None = Field(
        description="When the chat was created. Distinguish chats with the same topic."
    )
    members: list[ChatMember] | None = Field(
        description=(
            "Who is in the chat, returned only for unnamed chats — named chats show `topic` "
            + "instead, and this field is null there. Match a member by `display_name`, or by "
            + "`email` when `include_member_emails` is set; no member here carries a `user_id`, so "
            + "none can be compared against get_me's `user_id`."
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
        # Graph documents `topic` as absent when unnamed. A blank one survives the SDK as `""`.
        topic = chat.topic if chat.topic is not None and chat.topic.strip() else None
        members = _members(chat, include_member_emails) if topic is None else None
        meeting = chat.online_meeting_info
        return cls(
            chat_id=chat.id,
            # Not `.value`: `ChatType` subclasses `str`, and its generated members carry a trailing
            # comma, so `.value` is typed as a one-tuple.
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
            "The chats matching the request. The notes-to-self chat is usually the oneOnOne chat "
            + "whose only member is the user; confirm with get_me."
        )
    )
    capped: bool = Field(
        description=(
            "True when the walk stopped after collecting `limit` matches, so chats might remain "
            + "beyond what this call reached — with `chat_type` or `topic_contains` set, this "
            + "means more could still match. False means the entire chat list was walked: every "
            + "match already came back, so a short or empty list is the complete answer, not "
            + "evidence to look further."
        )
    )


async def list_recent_chats(
    client: GraphServiceClient,
    *,
    chat_type: ChatKind | None = None,
    topic_contains: str | None = None,
    limit: int,
    include_member_emails: bool,
) -> ChatList:
    assert 1 <= limit <= MAX_CHATS, f"limit must be within 1..{MAX_CHATS}, got {limit}"

    configuration = RequestConfiguration[_ChatsQuery](
        query_parameters=ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters(
            # Graph rejects `$select` on this collection. These expansions bring the fields back.
            expand=["members", "lastMessagePreview"],
            orderby=[_RECENCY],
            top=limit,
        )
    )
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.me.chats.get(request_configuration=configuration)
        assert first_page is not None, "Graph answered GET /me/chats with no collection"
        collected = await collect_pages(
            first_page, client, limit=limit, matches=_keeps(chat_type, topic_contains)
        )

    return ChatList(
        chats=[
            ChatSummary.from_chat(chat, include_member_emails=include_member_emails)
            for chat in collected.items
        ],
        capped=collected.capped,
    )


def _keeps(chat_type: ChatKind | None, topic_contains: str | None) -> Callable[[Chat], bool] | None:
    """What every returned chat must satisfy, or None when the caller asked for no narrowing."""
    checks: list[Callable[[Chat], bool]] = []
    if chat_type is not None:
        checks.append(_is_kind(chat_type))
    if topic_contains is not None:
        checks.append(_topic_holds(topic_contains))
    if not checks:
        return None
    return lambda chat: all(check(chat) for check in checks)


def _is_kind(chat_type: ChatKind) -> Callable[[Chat], bool]:
    """Whether the chat is of this kind, compared as enum members rather than as strings.

    `str()` of a `ChatType` member is `ChatType.OneOnOne`, not `oneOnOne`, so converting the other
    way is a bug that looks like the fix.
    """
    wanted = ChatType(chat_type)
    return lambda chat: chat.chat_type is wanted


def _topic_holds(fragment: str) -> Callable[[Chat], bool]:
    """Whether the chat's topic carries this text, case-insensitively.

    Graph records a topic for group chats only, so a topicless chat never matches and every
    one-to-one chat is silently excluded.
    """
    wanted = fragment.casefold()
    return lambda chat: chat.topic is not None and wanted in chat.topic.casefold()


def _members(chat: Chat, include_emails: bool) -> list[ChatMember]:
    return [
        ChatMember.from_conversation_member(member, include_email=include_emails)
        for member in chat.members or []
    ]


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List My Teams Chats",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def teams_list_chats(
        chat_type: Annotated[
            ChatKind | None,
            Field(
                description=(
                    "Only chats of this kind: `meeting`, `oneOnOne`, or `group`. Use `meeting` to "
                    + "find a meeting's chat, since it is the only kind carrying a `meeting_uri`. "
                    + "Omit it for every kind."
                )
            ),
        ] = None,
        topic_contains: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only chats whose topic contains this text, matched case-insensitively "
                    + "anywhere in it. Microsoft records a topic for group and meeting chats "
                    + "only, so this silently excludes every one-to-one chat."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_CHATS,
                description=(
                    f"How many chats to return, at most {MAX_CHATS}. The result is already the "
                    + "full answer for this call; calling again with the same arguments returns "
                    + "the same chats, not more — raise `limit` to see further back."
                ),
            ),
        ] = 25,
        include_member_emails: Annotated[
            bool,
            Field(
                description=(
                    "Include each member's email — needed to tell apart members who share a "
                    + "display name."
                )
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> ChatList:
        return await list_recent_chats(
            client,
            chat_type=chat_type,
            topic_contains=topic_contains,
            limit=limit,
            include_member_emails=include_member_emails,
        )
