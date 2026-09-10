"""`teams_list_chats` — the signed-in user's Teams chats, most recent first.

TRAP: Graph's `lastUpdatedDateTime` changes on a rename or a member change and is not recency. Only
the last message sent decides `last_message_at` and the sort order, which needs `Chat.Read` rather
than `Chat.ReadBasic`.

**`chat_type` and `topic_contains` narrow the rows here, never in `$filter`.** Microsoft lists
`$filter` among the supported query parameters for this collection and then enumerates no
filterable property, and it documents that an unsupported parameter can be dropped in silence
rather than refused (https://learn.microsoft.com/en-us/graph/query-parameters). So a
`chatType eq 'meeting'` is the ideal shape for a 200 OK carrying every chat under an argument that
named one kind. A predicate here cannot be dropped.

**Which is why `capped` exists, and why it had to come first.** `collect_pages` stops on `limit`
MATCHES rather than on `limit` rows, so a filtered walk really does reach a chat that has been
quiet for months — but when `limit` fills, the rows are "the matches among the ones read", and
that reads exactly like "the matches". Every other tool here that filters rows in process — both
mail listers, both calendar listers, both meeting-artifact listers — publishes the cap for that
reason. This one discarded it, so a full window of matches was indistinguishable from the end of
the list, on the deep-history lookup that is `topic_contains`'s whole purpose.
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

# The three kinds Microsoft names for a chat. `unknownFutureValue` is the evolvable-enum sentinel
# rather than a kind, so it is not offered here — the same reason rows report `unknown` for one
# this code cannot name.
type ChatKind = Literal["oneOnOne", "group", "meeting"]

type _ChatsQuery = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
List the signed-in user's Teams chats — one-to-one, group, and meeting — ordered by last message \
sent. Call it to see who is in a conversation, and when it was last active. Call it also for a \
meeting's `meeting_uri` — the only route to its transcripts and recordings. For that, narrow with \
`chat_type="meeting"` and, if the meeting's subject is known, `topic_contains`; there is no filter \
on `meeting_uri` itself. Either one searches the chat list until it has `limit` matches, so it \
reaches a conversation quiet for months — but read `capped` before reporting that no such chat \
exists, because true means it stopped on a full window. This tool does not list channel activity: \
teams_browse_channel walks one channel, teams_search_messages finds a message. Returns id, type, \
topic, last-message time, and members for unnamed chats.\
"""


class ChatMember(BaseModel):
    display_name: str | None = Field(
        description="The member's display name. Null for some external users."
    )
    email: str | None = Field(
        default=None,
        description=(
            "The member's email. When `include_member_emails` is set, this field is present. Null "
            + "for rooms or phone dial-ins."
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
            "Graph id for this chat (for example `19:...@thread.v2`). Microsoft puts this on every "
            + "message in the chat. Not a `teams:///` handle and cannot be assembled into one. "
            + "teams_read_message takes only a handle a tool result carries."
        )
    )
    chat_type: str = Field(
        description=(
            "`oneOnOne`, `group`, or `meeting`. If Graph reports a newer type, null becomes "
            + "`unknown`."
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
            + "to meeting. Pass it verbatim to teams_list_meeting_transcripts to find out whether "
            + "the "
            + "meeting was transcribed. Null when no join URL exists, in which case that "
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
            "Who is in the chat. Returned only for unnamed chats (where members are the name). "
            + "Null otherwise. A null field does not mean the chat has no members. It means "
            + "members are not returned for named chats. Do not use this incomplete list to make "
            + "decisions about chat membership. Match a member by display name, or by email with "
            + "`include_member_emails`. This list carries no user ids, so nothing in it can be "
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
        # Graph documents `topic` as absent when unnamed. A blank one survives the SDK as `""`.
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
            "The user's chats, most recent first. A full window can have more. A short one is "
            + f"all. Raise `limit` (up to {MAX_CHATS}) to see further back. The notes-to-self "
            + "chat is usually the oneOnOne chat whose only member is the user — call get_me to "
            + "confirm. When `chat_type` or `topic_contains` narrowed the answer, read `capped` "
            + "before reading a short list as "
            + '"there are no more".'
        )
    )
    capped: bool = Field(
        description=(
            "True when this call stopped with more chats still on offer, so a short answer is not "
            + "proof that nothing else matches. It is what tells a filtered answer apart from an "
            + "exhausted one. With `chat_type` or `topic_contains` set, the walk runs on until it "
            + "has `limit` matches, so true here means `limit` filled up and a higher one returns "
            + "more. False means the chat list itself ran out: what came back is every chat that "
            + 'matched, however few rows that is, and an empty answer then really is "there is '
            + 'no such chat".'
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

    The argument is resolved to a `ChatType` once, here, and never re-spelled per row. Two traps
    make that the shape worth having. `ChatType`'s generated members carry a trailing comma, so
    every one of them is declared as a one-tuple and the `str` mixin is what resolves it back to
    the wire value — which means a comparison against a string is correct at runtime and reads to
    a type checker as impossible. And `str()` of a member is `ChatType.OneOnOne`, not `oneOnOne`,
    so converting the other way is a bug that looks like the fix.

    A kind Microsoft adds after this code deserializes to None and matches nothing, which is
    right: it is not the kind that was asked for.
    """
    wanted = ChatType(chat_type)
    return lambda chat: chat.chat_type is wanted


def _topic_holds(fragment: str) -> Callable[[Chat], bool]:
    """Whether the chat's topic carries this text, case-insensitively.

    A chat with no topic is not a match. Microsoft documents `topic` as "Only available for group
    chats", so this silently excludes every one-to-one chat — which is what somebody hunting a
    named meeting wants, and is why the argument says so.
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
                    "Only chats of this kind: `meeting` for a meeting's own chat, `oneOnOne` for "
                    + "a direct conversation, `group` for a named or ad-hoc group. `meeting` is "
                    + "the one to reach for when the goal is a transcript or a recording, since "
                    + "this tool is the only route to a `meeting_uri` and a meeting chat is the "
                    + "only kind that carries one. Omit it for every kind. Applied to the chats "
                    + "this call read rather than by Microsoft 365, which publishes no filterable "
                    + "property here — so the walk keeps going until it has `limit` matches, "
                    + "rather than stopping after `limit` chats. Read `capped` before concluding "
                    + "there are no more."
                )
            ),
        ] = None,
        topic_contains: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only chats whose topic carries this text, matched case-insensitively "
                    + "anywhere in it. Use it to find a named conversation or a meeting by its "
                    + "subject — the route this tool's answer otherwise leaves to reading every "
                    + "`topic` by eye. Microsoft records a topic for group and meeting chats "
                    + "only, so this silently excludes every one-to-one chat. The search runs "
                    + "over the chat list itself, not just the newest `limit` of it, so it "
                    + "reaches a conversation that has been quiet for months. `capped` false "
                    + 'means it reached the end, and an empty answer then really is "no such '
                    + 'chat".'
                ),
            ),
        ] = None,
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
                    "Include each member's email. Off by default. When members share a display "
                    + "name, this is needed."
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
