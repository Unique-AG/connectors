"""`list_chats` — the signed-in user's Microsoft Teams chats, most recently active first.

The conversation side of Teams in one call, and the tool a model reaches for when the question
names a conversation rather than a keyword: which chats are live, who is in them, when each was
last posted in. No message text comes back here — nothing on this connector reads a chat's
messages — and the `chat_id` this returns is for *naming* a message somebody already found rather
than for asking a second question with.

Three Graph facts shape everything below, all from the list-chats reference
(https://learn.microsoft.com/en-us/graph/api/chat-list):

* `lastMessagePreview/createdDateTime desc` is the **only** ordering Graph will apply to this
  collection, and it is the one that means "recently active". The chat's own `lastUpdatedDateTime`
  looks like activity and is not: Graph documents it as when the chat was renamed or its membership
  last changed, so a chat nobody has posted in for a year can carry yesterday's timestamp. It is
  therefore not returned at all, and `last_message_at` — the value the order is actually by — is.
  `services/teams-mcp` reached the same conclusion the hard way ("order list_chats by recency").
* `$top` may be at most 50, and Graph warns that a page can come back short of `$top` with an
  `@odata.nextLink` still set — so filling a window needs the page walk `collect_pages` does, and a
  short first page is not evidence that there are no more chats.
* `$expand=members` returns at most 25 members per chat "even if a larger `$top` value is
  specified". The cap is silent and Graph sends no member total on this collection, which is exactly
  how a model comes to summarise a 200-person chat from 25 names. So a list that arrives full to the
  cap is reported as *possibly* incomplete — which is the whole of what is known: a chat with
  exactly 25 members and one with 200 come back identical.

**There is no cursor, and that is a decision rather than a gap.** `limit` (up to `MAX_CHATS`, which
is Graph's own `$top` ceiling here) is a *window* on the most recent chats: a cursor over a
collection that reorders itself on every message returns duplicates and gaps, and "the recent chats"
is what a window means. So "there is more" is said here the way it is said everywhere else on this
surface — as many chats as `limit` means the user may have more, fewer than `limit` is all of them —
and there is no flag saying it. That reading is only exactly true because the walk follows Graph's
paging to the end of the collection rather than believing a short page.

**This is also where a meeting is found, and why there is no meeting-discovery tool.** A meeting
chat is the conversation attached to a Teams meeting, so it is already in this list with the
meeting's subject as its `topic` and its recency to order by — and `chat.onlineMeetingInfo` is in
this collection's *default* projection, so the join URL behind it costs no extra request, no extra
permission and no Microsoft calendar read. That URL is the only value a delegated caller is given
that addresses the `onlineMeeting` behind the chat, and it is what the meeting handle carries.
Turning it into one is `shared/handles.py`'s job and never this file's: a handle is how one tool's
answer becomes another tool's argument, which works only while there is exactly one speller of each
shape. This module asks that speller for the handle, and reports its `None` as the first-class
outcome it is — Graph gave no join URL, so this connector cannot address that meeting at all and
nothing is invented from the chat id to stand in.

`Chat.Read` rather than the least-privileged `Chat.ReadBasic` because ordering by recency needs
`$expand=lastMessagePreview`, and a message preview is a message — which "read the names and members
of chats" does not cover.
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

# The delegated Graph permissions this tool calls under. The registry unions every tool's, which is
# what sign-in asks Entra to consent to, and a refusal is worded from this same tuple. `Chat.Read`
# and not `Chat.ReadBasic` — "read the names and members of chats" — because listing by recency
# needs `$expand=lastMessagePreview`, and a message preview is a message. The name comes from
# `shared/handles.py` because which Teams surface a permission covers is that module's knowledge,
# and a permission spelled out in two files is one that can be misspelled in one of them. The tuple
# below is still this tool's own declaration and is what its refusals are worded from.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION,)

# Built once at import: a call inside a parameter default rebuilds the descriptor on every
# registration and is a lint error in both of this repo's checkers.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# Graph's documented `$top` ceiling on this collection. The tool's schema derives its `limit`
# maximum from this, so the bound a caller sees is the bound Graph actually enforces.
MAX_CHATS = 50

# Graph's documented cap on `$expand=members`, per chat.
MEMBERS_PER_CHAT = 25

_RECENCY = "lastMessagePreview/createdDateTime desc"

type _ChatsQuery = ChatsRequestBuilder.ChatsRequestBuilderGetQueryParameters

_DESCRIPTION = f"""\
List the Microsoft Teams chats the signed-in user is a member of — one-to-one, group and meeting \
chats — most recently active first, with each chat's id, type, topic, last-message time and (for \
unnamed chats) its members.

Reach for this to see which conversations are live, who is in them, and when each was last posted \
in — never for what was said in them: no message text is returned here, and no tool on this server \
reads a chat's messages. The other use is naming: a `chat_id` here is the id Microsoft puts on \
every message in that chat, so this list is how a message found elsewhere gets a topic and a set \
of participants. It is not an argument to anything — no tool here takes a chat id. This returns \
chats only: Teams channels live inside teams and are a different surface, which this server does \
not list.

**This is also how a meeting is found.** A `meeting` chat is the conversation attached to a Teams \
meeting, its `topic` is the meeting's subject, and it carries `meeting_uri` — a handle for the \
meeting behind that conversation. So "the pricing call last Tuesday" is identified here, by topic \
and by recency: there is no separate meeting-search tool because this list already answers which \
meeting, and no Microsoft calendar permission is involved. No tool on this server takes that \
handle as an argument, so today it names a meeting rather than opening one. `meeting_uri` is null \
on every non-meeting chat, and null on a meeting chat Microsoft returned no join URL for — nothing \
else this connector has addresses that meeting, so there is no other route to try.

Ordering and `last_message_at` both come from the last message actually sent in the chat, which is \
the only notion of recency Microsoft Graph will sort this collection by. The chat property that \
looks like activity — Graph's `lastUpdatedDateTime` — is not returned here on purpose: Graph \
defines it as when the chat was renamed or its membership changed, so a chat nobody has posted in \
for a year can carry yesterday's timestamp. `last_message_at` is null for a chat with no messages.

`members` is returned only for chats whose `topic` is null, because those chats have no other \
name; Graph caps that list at {MEMBERS_PER_CHAT} members per chat and sends no member \
total, so `members_may_be_incomplete` says when a list came back full to that cap — people may \
be missing from it, and Graph will not say whether they are. Set `include_member_emails` when \
two members share a display name.

There is no pagination and no cursor. `limit` is a window on the most recent chats: getting that \
many back means the user may have more, and getting fewer back means those are all of their \
chats — this walks Microsoft's paging to the end of the collection rather than trusting a short \
page. Widen \
`limit` (up to {MAX_CHATS}, Graph's own maximum for this collection) to see further back. \
The signed-in user's own notes-to-self \
chat is usually the oneOnOne chat whose only member is them (call get_me to know who that is; a \
member is matched by display name or, with `include_member_emails`, by email — this list carries \
no user ids).\
"""


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
            "The chat's Graph id, e.g. `19:...@thread.v2`. It is the id Microsoft puts on every "
            + "message in this chat, so it is how to tell which of these chats a message found "
            + "elsewhere came from. No tool here takes a chat id as an argument, it is not one of "
            + "this connector's `teams:///` handles and cannot be assembled into one, and it "
            + "cannot be reconstructed from a topic or a member's name either."
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
    meeting_uri: str | None = Field(
        description=(
            "For a meeting chat, a handle for the Teams meeting behind it. This is the only route "
            + "from a conversation to the meeting itself: Microsoft addresses a meeting by the "
            + "join URL this handle carries, and nothing turns a chat id, a topic or a date into "
            + "one. No tool on this server takes it as an argument, so it identifies a meeting "
            + "rather than opening one.\n"
            + "Null for every chat whose `chat_type` is not `meeting`, and also null for a meeting "
            + "chat Microsoft returned no join URL for — in which case nothing this connector has "
            + "addresses that meeting, there is no other route to try, and the honest answer is to "
            + "say so rather than to search for one."
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
    members_may_be_incomplete: bool = Field(
        description=(
            f"True when `members` came back full to Microsoft Graph's cap of {MEMBERS_PER_CHAT} "
            + "members per chat on this endpoint, so the chat may have members that were not "
            + "returned. It is not proof that any were: Graph sends no member total here, so a "
            + f"chat with exactly {MEMBERS_PER_CHAT} members is indistinguishable from one with "
            + 'hundreds. Either way, do not answer "who is in this chat" from a list this is '
            + "set on. Always false when `members` is null."
        )
    )


class ChatList(BaseModel):
    chats: list[ChatSummary] = Field(
        description=(
            "The signed-in user's chats, most recently active first. As many as `limit` means the "
            + "user may have more; fewer than `limit` is every chat there is, because the walk "
            + "follows Microsoft's paging to the end of the collection rather than believing a "
            + f"short page. There is no cursor: raise `limit` (up to {MAX_CHATS}) to widen the "
            + "window, and chats less recent than it are not reachable from this tool."
        )
    )


async def list_recent_chats(
    client: GraphServiceClient, *, limit: int, include_member_emails: bool
) -> ChatList:
    """The `limit` most recently active chats.

    Whether the user has more than that is not reported as a flag: the walk follows Graph's paging
    to the end of the collection, so a full window may hold more behind it and a short one is the
    whole of it — which is what a page size means everywhere else and what a model reads it as.
    """
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

    return ChatList(chats=[_summarise(chat, include_member_emails) for chat in collected.items])


def _summarise(chat: Chat, include_member_emails: bool) -> ChatSummary:
    assert chat.id is not None, "Graph returned a chat with no id"
    preview = chat.last_message_preview
    members = _members(chat, include_member_emails) if chat.topic is None else None
    # `ChatType` subclasses `str`, so the member *is* its wire value ("group") and pydantic
    # narrows it to a plain `str` on the way in. Its `.value` would be the obvious thing to reach
    # for and is typed as a one-tuple, because the generated members carry trailing commas
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


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this tool against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tool
    borrows it per call and never owns it. `create_app` closes it on shutdown.
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
                    "How many chats to return, most recently active first. Default 25, maximum "
                    + f"{MAX_CHATS} — Microsoft Graph refuses a larger page on this "
                    + "collection."
                ),
            ),
        ] = 25,
        include_member_emails: Annotated[
            bool,
            Field(
                description=(
                    "Include each listed member's email address. Off by default: it is only "
                    + "needed to tell apart two members with the same display name."
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
