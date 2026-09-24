"""`teams_search_messages` — full-text search across every Teams message the signed-in user can see.

`POST /search/query` with `entityTypes: ["chatMessage"]` is Graph's only full-text path over Teams
messages, delegated context only
(https://learn.microsoft.com/en-us/graph/search-concept-chat-messages). A hit is a projection with
no `body`. `total` counts the page rather than the matches, so only `moreResultsAvailable` says
whether to keep going. No custom sort is supported. Paging is stateless `from`/`size` integers
rather than an `@odata.nextLink`, so `collect_pages` has no part here.

Graph throttles reads on a chat or channel to one request per second, per app, per tenant
(https://learn.microsoft.com/en-us/graph/throttling). That budget belongs to the app, not to the
caller. As a result, one user's wide sweep degrades every other user in the tenant.

`include_body` trades that budget for fewer round trips. Each addressable hit gets its own
`teams_read_message`-shaped GET request, with the same endpoint, the same permissions, and the
same normalization. This is capped at `_HYDRATION_CONCURRENCY` requests in flight. As a result, a
page of `MAX_RESULTS` hits that share one busy channel cannot burn through the app's whole
one-a-second allowance on a single call. That still costs up to `size` extra requests, and however
long the slowest of them takes. This goes against the "exactly one Graph request" that this tool
otherwise promises. So `include_body` defaults to off. A caller that only wants to know *whether*
a message exists does not need to pay Graph's latency for text that nobody asked for. Neither does
a caller that is satisfied with Microsoft's `summary`. Graph can refuse a hit because the message
was deleted, or because it is not visible. For a hit on a channel reply, Graph can also refuse it
because the reply is addressed under the wrong post (see `MessageHit.uri`). A hit that Graph
refuses to hydrate keeps its `summary` and its handle. For that hit, only `text` and `reactions`
stay unset, exactly as if `include_body` was off just for it.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from typing import Annotated, Self
from uuid import UUID

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.entity_type import EntityType
from msgraph.generated.models.search_hit import SearchHit
from msgraph.generated.models.search_hits_container import SearchHitsContainer
from msgraph.generated.models.search_query import SearchQuery
from msgraph.generated.models.search_request import SearchRequest
from msgraph.generated.search.query.query_post_request_body import QueryPostRequestBody
from msgraph.generated.search.query.query_post_response import QueryPostResponse
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step
from office_365_mcp.shared.handles import (
    CHANNEL_PERMISSION,
    CHAT_PERMISSION,
    MessageHandle,
    message_handle,
)
from office_365_mcp.shared.kql import flag, free_text, quoted
from office_365_mcp.shared.messages import (
    MAX_REPLIES_PER_POST,
    MessageReaction,
    MessageSender,
    TeamsMessage,
)
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import as_utc

TOOL_NAME = "teams_search_messages"

STEP_SEARCH = "search_query"
# `include_body` reuses the same two step names that `teams_read_message` counts its own reads
# under. `include_body` makes exactly that Graph call, on this tool's behalf. As a result, "reading
# one chat message" stays one comparable series, whichever tool reached it. This tool does not
# fork a second, tool-specific name for an identical request shape. A hit never carries a reply's
# own handle (see `MessageHit.uri`), so hydration has no third, `channel_reply` path to reuse.
STEP_CHAT_MESSAGE = "chat_message"
STEP_CHANNEL_MESSAGE = "channel_message"

# TRAP: `/search/query` accepts `Chat.Read` alone and then silently covers chats only. This tool
# requests both permissions. As a result, a tenant that withholds the broad one is refused at
# consent time, not at query time.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "release"}

# Graph publishes no `size` ceiling for `chatMessage`. The usual ceiling is 1000, or 25 for
# `message`/`event`.
MAX_RESULTS = 50

# Graph throttles a chat or channel to about one request per second, per app, per tenant (see the
# module docstring). That budget is shared with every other caller of this connector. Hydration
# stays well under that budget, even though `MAX_RESULTS` hits can share one busy channel.
_HYDRATION_CONCURRENCY = 3

_DESCRIPTION = """\
This tool searches every Teams message the signed-in user can see, by keyword, sender, mention, \
date, attachment, or read state. The order is not guaranteed. This tool answers a "find the \
message where…" question and any date-bounded question. teams_browse_channel is the sibling for \
reading one channel's posts directly, but it has no date filter. This tool covers any \
date-bounded question instead, including for a named channel.

Notes:
- At least one search criterion is required. Every given criterion is ANDed together.
- It takes no chat or channel scope, and it searches every chat and channel the user can see. \
Read `channel_id` or `chat_id` on each hit to see where it came from.
- Unless `include_body` is set, a hit carries only metadata and Microsoft's `summary` snippet, \
never the message body. Pass a hit's `uri` to teams_read_message for the actual words either way.\
"""


class MessageHit(BaseModel):
    """One matched message: all Graph's search index will say about it, and how to read the rest."""

    uri: str | None = Field(
        description=(
            "A handle for this exact message, for example "
            + "`teams:///chats/{chatId}/messages/{messageId}` or "
            + "`teams:///teams/{teamId}/channels/{channelId}/messages/{messageId}`, with each id "
            + "percent-encoded. Pass it verbatim to teams_read_message. This handle is the only "
            + "route to the attachments and the mentions. Unless `include_body` was set, it is "
            + "also the only route to the full text. When a hit carries neither a chat identity "
            + "nor a channel identity, this value is null, and that hit is then unaddressable, "
            + "`include_body` included. When the hit is a reply, this handle addresses its parent "
            + "post instead, and teams_read_message then reports that it cannot read the "
            + "message. `include_body` hits the same wall, and leaves `text` unset for it. Only "
            + "teams_browse_channel emits a reply's own handle, and it reaches just the newest "
            + f"{MAX_REPLIES_PER_POST} replies of each post, with no further cursor. Outside "
            + "that window, there is no route to the full text. A second browse of that channel "
            + "returns the same window. Report the `summary` with the sender and date. Then stop "
            + "looking."
        )
    )
    message_id: str = Field(
        description=(
            "Graph message `id`. Unique within its chat or channel only. Use `uri` to identify "
            + "a message globally."
        )
    )
    chat_id: str | None = Field(
        description=(
            "Chat this message is in, unencoded, for example `19:...@thread.v2`. Same as "
            + "teams_list_chats reports. Null for channel messages."
        )
    )
    team_id: str | None = Field(
        description="The team a channel message belongs to. Null for a chat message."
    )
    channel_id: str | None = Field(
        description="The channel a channel message was posted in. Null for a chat message."
    )
    subject: str | None = Field(
        description="Message subject. Usually null: Teams sets it only on some channel root posts."
    )
    summary: str | None = Field(
        description=(
            "Microsoft's own snippet of the matching text, truncated with `...` where it was "
            + "cut. It is not the full message. Do not quote it as the whole message. Do not "
            + "infer anything from its absence. See `uri` instead."
        )
    )
    sender: MessageSender = Field(description="Who sent the message.")
    created_at: datetime | None = Field(
        description=(
            "When sent. Compare this across hits to order them. Graph applies no sort of its "
            + "own to message search."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When the message was last modified — Microsoft counts a reaction change as a "
            + "modification, so a difference from `created_at` is not evidence of an edit. "
            + "teams_read_message's `last_edited_at` is what backs Teams' own 'Edited' flag."
        )
    )
    importance: str | None = Field(
        description="`normal`, `high` or `urgent`, as the sender marked the message."
    )
    web_url: str | None = Field(
        description=(
            "A link that opens the message in Microsoft Teams. It is populated for channel "
            + "messages. It is null for chat messages. Use `uri` for those instead."
        )
    )
    text: str | None = Field(
        description=(
            "The message as plain text, normalized the same way teams_read_message reports it — "
            + "null unless `include_body` was set. Even then, null does not mean no text. It "
            + "also covers a hit that `include_body` did not hydrate (see `uri`). It also covers "
            + "a message that genuinely has none, for example a system event or an image-only "
            + "post. Fall back to `summary`, or call teams_read_message with `uri`, rather than "
            + "reading a null here as silence."
        )
    )
    reactions: list[MessageReaction] = Field(
        description=(
            "Unless `include_body` was set and Graph answered, this is empty. It shows who "
            + "reacted to this message, and with what. Search's own index carries no reactions "
            + "at all. As a result, this list is populated from the same hydration that fills "
            + "`text`. An empty list here has the same three readings that `text`'s null value "
            + "does: nobody reacted, `include_body` was not set, or hydration did not reach this "
            + "hit."
        )
    )

    @classmethod
    def from_hit(cls, hit: SearchHit) -> Self | None:
        resource = hit.resource
        if not isinstance(resource, ChatMessage) or resource.id is None:
            return None
        sender = MessageSender.from_identity(resource.from_)
        if sender is None:
            # Graph nulls the identity on a deleted message or a system event. The retrievable set
            # holds neither `messageType` nor `eventDetail`, so this is the only signal.
            return None
        channel = resource.channel_identity
        team_id = channel.team_id if channel is not None else None
        channel_id = channel.channel_id if channel is not None else None
        return cls(
            uri=_hit_uri(
                message_id=resource.id,
                chat_id=resource.chat_id,
                team_id=team_id,
                channel_id=channel_id,
            ),
            message_id=resource.id,
            chat_id=resource.chat_id,
            team_id=team_id,
            channel_id=channel_id,
            subject=resource.subject,
            summary=hit.summary,
            sender=sender,
            created_at=resource.created_date_time,
            last_modified_at=resource.last_modified_date_time,
            # `ChatMessageImportance` subclasses `str`, so the member is its own wire value.
            importance=resource.importance,
            web_url=resource.web_url,
            # Filled in by `_hydrated` when `include_body` asked for it. Search's own retrievable
            # properties for `chatMessage` carry neither
            # (https://learn.microsoft.com/en-us/graph/search-concept-chat-messages).
            text=None,
            reactions=[],
        )


class MessageSearchResults(BaseModel):
    messages: list[MessageHit] = Field(
        description=(
            "The matched messages on this page. Messages with no sender are dropped. Graph "
            + 'names no author on a system message, for example "Ada joined," or on a deleted '
            + "message. A message absent here is not proof that it does not exist."
        )
    )
    next_offset: int | None = Field(
        description=(
            "This is the offset that reaches the next page. When it cannot advance further, "
            + "this is null instead. Either no more results exist, or the page held no hits to "
            + "advance past even though Graph said more remain. Do not reuse this offset either "
            + "way. It counts Graph's hits, not the messages this tool returned."
        )
    )


@dataclass(frozen=True, slots=True)
class SearchCriteria:
    """What to match, before it becomes a query string. Microsoft ANDs every field together."""

    query: str | None = None
    sender: str | None = None
    recipient: str | None = None
    mentions: UUID | None = None
    sent_after: date | datetime | None = None
    sent_before: date | datetime | None = None
    has_attachment: bool | None = None
    is_read: bool | None = None
    mentions_me: bool | None = None

    @property
    def is_empty(self) -> bool:
        return not _query_string(self)


CRITERIA: tuple[str, ...] = tuple(field.name for field in fields(SearchCriteria))

_NO_CRITERIA = (
    "teams_search_messages needs at least one of "
    + ", ".join(CRITERIA)
    + ". A search with none of them returns an arbitrary sample of every message the user "
    + "can see, not an answer. Add the keywords, person, or date range the question is about."
)


def _query_string(criteria: SearchCriteria) -> str:
    """The `queryString` these criteria become. Empty exactly when nothing was asked for.

    The term names and their odd casing are Microsoft's own for `chatMessage`. `sent` is a
    comparison rather than a `term:value` pair. A query of nothing but punctuation contributes no
    term, which is why this string, not the arguments behind it, is what `is_empty` tests.
    """
    terms: list[str] = []
    if criteria.query:
        rendered = free_text(criteria.query)
        if rendered:
            terms.append(rendered)
    if criteria.sender:
        terms.append(f"from:{quoted(criteria.sender)}")
    if criteria.recipient:
        terms.append(f"to:{quoted(criteria.recipient)}")
    if criteria.mentions is not None:
        # Graph matches a user id with the dashes stripped, which is exactly `UUID.hex`.
        terms.append(f"mentions:{criteria.mentions.hex}")
    if criteria.sent_after is not None:
        terms.append(f"sent>={_kql_moment(criteria.sent_after)}")
    if criteria.sent_before is not None:
        terms.append(f"sent<={_kql_moment(criteria.sent_before)}")
    if criteria.has_attachment is not None:
        terms.append(f"hasAttachment:{flag(criteria.has_attachment)}")
    if criteria.is_read is not None:
        terms.append(f"IsRead:{flag(criteria.is_read)}")
    if criteria.mentions_me is not None:
        terms.append(f"IsMentioned:{flag(criteria.mentions_me)}")
    return " ".join(terms)


def _kql_moment(bound: date | datetime) -> str:
    """One of KQL's documented datetime literal formats: a whole day, or a second.

    KQL accepts no `+00:00` offset. So this function converts an aware moment to UTC, and writes
    it with a literal `Z`. A relabel instead of a conversion moves the bound. `as_utc` only
    supplies the zone a naive moment lacks. `datetime` must be checked first: it subclasses
    `date`, and the other order silently discards the time.
    """
    if isinstance(bound, datetime):
        return f"{as_utc(bound).astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"
    return bound.isoformat()


async def teams_search_messages(
    client: GraphServiceClient,
    *,
    criteria: SearchCriteria,
    offset: int,
    size: int,
    include_body: bool = False,
) -> MessageSearchResults:
    """One page of matches for `criteria`. This is exactly one Graph request, whatever the
    criteria. When `include_body` is set, it costs one more request per addressable hit. See the
    module docstring for what that second part costs and how a hit it cannot reach is handled.
    """
    query = _query_string(criteria)
    assert query, (
        "teams_search_messages needs at least one criterion. The tool refuses an empty set."
    )
    assert 1 <= size <= MAX_RESULTS, f"size must be within 1..{MAX_RESULTS}, got {size}"
    assert offset >= 0, f"offset must not be negative, got {offset}"

    body = QueryPostRequestBody(
        requests=[
            SearchRequest(
                entity_types=[EntityType.ChatMessage],
                query=SearchQuery(query_string=query),
                from_=offset,
                size=size,
            )
        ]
    )
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_SEARCH):
            response = await client.search.query.post(body)

        assert response is not None, "Graph answered POST /search/query with no response"
        container = _hits_container(response)
        hits = (container.hits or []) if container is not None else []
        more_to_come = bool(container.more_results_available) if container else False

        messages = [
            message for message in (MessageHit.from_hit(hit) for hit in hits) if message is not None
        ]
        if include_body:
            messages = await _hydrated(client, messages)

    return MessageSearchResults(
        messages=messages,
        # `moreResultsAvailable` alone is not a safe signal for a next page. A hitless page still
        # hands back the offset it was asked at. A caller that follows `next_offset` on that
        # signal alone requests that same offset forever.
        next_offset=offset + len(hits) if more_to_come and hits else None,
    )


async def _hydrated(client: GraphServiceClient, hits: list[MessageHit]) -> list[MessageHit]:
    """This returns `hits`, each with its own `text` and `reactions` where Graph answers for it.

    This work is concurrent, bounded to `_HYDRATION_CONCURRENCY`. Per-hit failures are absorbed
    here rather than raised. Graph can refuse one hit — deleted, not visible, or a reply
    addressed under the wrong post — and that must not cost the whole page. `teams_browse_channel`
    applies the same principle to a dropped system message. A failure that this connector does
    not classify still raises. This is because that is a bug to see rather than a hit to skip.
    """
    semaphore = asyncio.Semaphore(_HYDRATION_CONCURRENCY)

    async def hydrated_hit(hit: MessageHit) -> MessageHit:
        handle = message_handle(hit.uri) if hit.uri is not None else None
        if handle is None:
            return hit
        async with semaphore:
            try:
                message = await _fetch(client, handle)
            except GraphFailure:
                return hit
        assert message is not None, "Graph answered a message read with no message"
        full = TeamsMessage.from_message(message, handle=handle)
        return hit.model_copy(update={"text": full.text, "reactions": full.reactions})

    return list(await asyncio.gather(*(hydrated_hit(hit) for hit in hits)))


async def _fetch(client: GraphServiceClient, handle: MessageHandle) -> ChatMessage | None:
    """The message `handle` addresses — `teams_read_message`'s own two non-reply branches, since a
    hit never carries a reply's own handle (see `MessageHit.uri`)."""
    if handle.chat_id is not None:
        with graph_step(STEP_CHAT_MESSAGE):
            return await (
                client.chats.by_chat_id(handle.chat_id)
                .messages.by_chat_message_id(handle.message_id)
                .get()
            )
    assert handle.team_id is not None and handle.channel_id is not None, (
        "a hit's handle addresses either a chat or a team channel"
    )
    with graph_step(STEP_CHANNEL_MESSAGE):
        return await (
            client.teams.by_team_id(handle.team_id)
            .channels.by_channel_id(handle.channel_id)
            .messages.by_chat_message_id(handle.message_id)
            .get()
        )


def _hits_container(response: QueryPostResponse) -> SearchHitsContainer | None:
    """The one container this request produces: Graph accepts a single `searchRequest` at a time.
    This one names a single entity type, so the nesting holds one of each.
    """
    for search_response in response.value or []:
        for container in search_response.hits_containers or []:
            return container
    return None


def _hit_uri(
    *, message_id: str, chat_id: str | None, team_id: str | None, channel_id: str | None
) -> str | None:
    if team_id is not None and channel_id is not None:
        return MessageHandle(message_id=message_id, team_id=team_id, channel_id=channel_id).uri
    if chat_id is not None:
        return MessageHandle(message_id=message_id, chat_id=chat_id).uri
    return None


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Search Teams Messages",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def search_teams_messages(
        query: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Keywords to find. Every word must appear, in any order, unless quoted for "
                    + 'adjacency. `"release notes"` matches only words side by side. `release '
                    + "notes` without quotes matches the words anywhere. This tool treats any "
                    + "search-operator syntax as literal text, not as a command. Use the other "
                    + "parameters to filter instead."
                ),
            ),
        ] = None,
        sender: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only messages from this person, by name, alias or email. Prefer this over "
                    + "naming the person in `query`, which matches mentions too."
                ),
            ),
        ] = None,
        recipient: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only messages addressed to this person. This works only for one-to-one "
                    + "chats. It hides group and channel matches."
                ),
            ),
        ] = None,
        mentions: Annotated[
            UUID | None,
            Field(
                description=(
                    "Only messages that @-mention this user, by Entra object id (the `user_id` "
                    + "of a sender or from get_me). Names do not work: Microsoft matches on the "
                    + "id alone."
                )
            ),
        ] = None,
        sent_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only messages sent at or after this point, inclusive. A date (`2026-03-04`) "
                    + "bounds the whole day. A moment (`2026-03-04T09:00:00Z`) bounds the exact "
                    + "second. This tool reads a moment with no time zone as UTC."
                )
            ),
        ] = None,
        sent_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only messages sent at or before this point, inclusive, in the same two "
                    + "shapes as `sent_after`. A moment bounds the exact second. A date bounds "
                    + "the whole day."
                )
            ),
        ] = None,
        has_attachment: Annotated[
            bool | None,
            Field(
                description=(
                    "True: messages with attachments. False: messages without. Omit to search both."
                )
            ),
        ] = None,
        is_read: Annotated[
            bool | None,
            Field(description=("True: read by the user. False: unread. Omit to search both.")),
        ] = None,
        mentions_me: Annotated[
            bool | None,
            Field(description=("True: @-mentions the user. False: does not. Omit to search both.")),
        ] = None,
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "How many results to skip. Start at 0. Pass the previous response's "
                    + "`next_offset` to advance."
                ),
            ),
        ] = 0,
        size: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=f"Results per page, at most {MAX_RESULTS}.",
            ),
        ] = 25,
        include_body: Annotated[
            bool,
            Field(
                description=(
                    "Inline each hit's full text and reactions instead of leaving them for a "
                    + "separate teams_read_message call. This costs up to one more Graph request "
                    + "per hit on this page. Leave it off for a quick scan of `summary`. When the "
                    + "words themselves are what this call is for, set it."
                )
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> MessageSearchResults:
        criteria = SearchCriteria(
            query=query,
            sender=sender,
            recipient=recipient,
            mentions=mentions,
            sent_after=sent_after,
            sent_before=sent_before,
            has_attachment=has_attachment,
            is_read=is_read,
            mentions_me=mentions_me,
        )
        if criteria.is_empty:
            raise ToolError(_NO_CRITERIA)
        return await teams_search_messages(
            client,
            criteria=criteria,
            offset=offset,
            size=size,
            include_body=include_body,
        )
