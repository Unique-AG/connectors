"""`teams_search_messages` — full-text search across every Teams message the signed-in user can see.

`POST /search/query` with `entityTypes: ["chatMessage"]` is the only full-text path Graph offers
over Teams messages, and it runs in delegated context only
(https://learn.microsoft.com/en-us/graph/search-concept-chat-messages). Four of its documented
properties shape everything below.

* **The hit is a projection, not a message.** The retrievable set is `channelIdentity`, `chatId`,
  `createdDateTime`, `etag`, `from`, `id`, `importance`, `lastModifiedDateTime`, `subject` and
  `webUrl`, with no `body`.
* **`total` is not a match count.** Graph puts the number of results on the page in it, so nothing
  here reads it. `moreResultsAvailable` is its only "keep going" signal.
* **Sorting is unsupported.** Graph supports no custom sort for `chatMessage`.
* **Paging is stateless.** `from`/`size` integers rather than an opaque `@odata.nextLink`, so
  `graph_client.collect_pages` has no part here.

Deliberately absent: the per-chat scan the connector this one replaces falls back to. Graph caps
reads at one request per second per app per tenant on a given channel or chat
(https://learn.microsoft.com/en-us/graph/throttling), and the budget is per app, so one user's
sweep of fifty chats degrades every other user in the tenant.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.tools import tool as tool_metadata
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

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import CHANNEL_PERMISSION, CHAT_PERMISSION, MessageHandle
from office_365_mcp.shared.kql import flag, free_text, quoted
from office_365_mcp.shared.messages import MAX_REPLIES_PER_POST, MessageSender
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_search_messages"

STEP = "search_query"

# TRAP: `/search/query` accepts `Chat.Read` alone, and a search never returns more than the
# equivalent GET would, so without `ChannelMessage.Read.All` it silently covers chats only. Both are
# requested, so a tenant withholding the broad one is refused at consent time, not at query time.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "release"}

# Graph documents a general `size` maximum of 1000 and caps the `message` and `event` entities at
# 25. It publishes no ceiling for `chatMessage`, so 50 is an undocumented choice between the two.
MAX_RESULTS = 50

_DESCRIPTION = """\
Search every Teams message the signed-in user can see, by keyword, sender, mention, date, \
attachment or read state. Use it for "find the message where…" and for every date-bounded \
question, including one about a named channel — browse_channel has no date filter. Search takes \
no chat or channel scope: read `channel_id` on each hit to see where it came from. At least one \
criterion is required and all are ANDed. Hits carry metadata and Microsoft's `summary` snippet \
only — pass a hit's `uri` to teams_read_message for the actual words.\
"""


class MessageHit(BaseModel):
    """One matched message: all Graph's search index will say about it, and how to read the rest."""

    uri: str | None = Field(
        description=(
            "A handle for this exact message, e.g. "
            + "`teams:///chats/{chatId}/messages/{messageId}` or "
            + "`teams:///teams/{teamId}/channels/{channelId}/messages/{messageId}`, with each id "
            + "percent-encoded. Pass it verbatim to teams_read_message; this search returns no "
            + "message "
            + "body, so it is the only route to the full text, the attachments and the mentions. "
            + "Null in the rare case where Graph returned a hit with neither a chat nor a channel "
            + "identity, which cannot be addressed at all. "
            + "One handle here can fail to read: Microsoft "
            + "addresses a reply in a channel thread under its parent post and its search index "
            + "does not say which post that is, so a hit that is a reply gets the root-post form "
            + "above and teams_read_message may answer that it could not be read. browse_channel "
            + "is the "
            + "only tool that emits a reply's own handle, and it reaches only the newest "
            + f"{MAX_REPLIES_PER_POST} replies of each post on the channel's first page, following "
            + "no cursor further back. If "
            + "the reply is not in that window there is no route to its full text and browsing "
            + "again returns the same window: report this `summary` with the sender and date "
            + "here, say the full text could not be retrieved, and stop looking."
        )
    )
    message_id: str = Field(
        description=(
            "Graph message `id`. Unique within its chat or channel only; use `uri` to identify "
            + "a message globally."
        )
    )
    chat_id: str | None = Field(
        description=(
            "Chat this message is in, unencoded, e.g. `19:...@thread.v2`. Same as list_chats "
            + "reports. Null for channel messages."
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
            "Microsoft's own snippet of the matching text, truncated with `...` where it was cut. "
            + "This is the ONLY message content this search returns — Graph's search projection "
            + "has no body — so do not quote it as the whole message or infer from its absence. "
            + "Read `uri` for the real text."
        )
    )
    sender: MessageSender = Field(description="Who sent the message.")
    created_at: datetime | None = Field(
        description=(
            "When sent. Compare this to order results: Graph does not sort message search."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When the message was last modified. Microsoft counts adding or removing a reaction "
            + "as a modification, so a difference from `created_at` is not evidence of an edit — "
            + "teams_read_message reports `last_edited_at`, which is the property behind Teams' "
            + "own "
            + "'Edited' flag and is what to read when an edit is the question."
        )
    )
    importance: str | None = Field(
        description="`normal`, `high` or `urgent`, as the sender marked the message."
    )
    web_url: str | None = Field(
        description=(
            "A link that opens the message in Microsoft Teams. Populated for channel messages and "
            + "null for chat messages, which Graph gives no such link — use `uri` to read those."
        )
    )

    @classmethod
    def from_hit(cls, hit: SearchHit) -> Self | None:
        resource = hit.resource
        if not isinstance(resource, ChatMessage) or resource.id is None:
            return None
        sender = MessageSender.from_identity(resource.from_)
        if sender is None:
            # Graph documents the identity as null for a deleted message or a Teams system event.
            # The retrievable set holds neither `messageType` nor `eventDetail`, so a missing sender
            # is the only signal, and such a hit carries no text either.
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
        )


class MessageSearchResults(BaseModel):
    messages: list[MessageHit] = Field(
        description=(
            "Matching messages on this page, from ANY participant — not only the signed-in "
            + "user's own. Every chat and channel the user can see was searched, and nothing "
            + "narrows a search to one of them. Messages with no sender are dropped: Graph names "
            + 'no author on a system message ("Ada joined") or on a deleted one, so a message '
            + "absent here is not a message that does not exist."
        )
    )
    next_offset: int | None = Field(
        description=(
            "The offset that reaches the next page of results, or null when the page cannot "
            + "advance further. Null means either no more results exist, or the page held no hits "
            + "to advance past even though Graph said more may exist — in both cases, do not use "
            + "this offset again. It counts Graph's hits, not the messages this tool returned, "
            + "because offsets index Graph's unfiltered results."
        )
    )


@dataclass(frozen=True, slots=True)
class SearchCriteria:
    """What to match, before it becomes a query string. Microsoft ANDs every field together."""

    query: str | None = None
    sender: str | None = None
    recipient: str | None = None
    mentions: UUID | None = None
    sent_after: date | None = None
    sent_before: date | None = None
    has_attachment: bool | None = None
    is_read: bool | None = None
    mentions_me: bool | None = None

    @property
    def is_empty(self) -> bool:
        return not _query_string(self)


CRITERIA: tuple[str, ...] = tuple(field.name for field in fields(SearchCriteria))

# TRAP: Graph answers a criteria-free search with an arbitrary slice of everything the user can
# read, and that slice reads like a real result set — the one failure a model cannot detect.
_NO_CRITERIA = (
    "teams_search_messages needs at least one of "
    + ", ".join(CRITERIA)
    + ". Searching with none of them would return an arbitrary sample of every message the user "
    + "can see, not an answer. Add the keywords, person or date range the question is about."
)


def _query_string(criteria: SearchCriteria) -> str:
    """The `queryString` these criteria become. Empty exactly when nothing was asked for.

    The scope terms below, and their odd casing, are Microsoft's own for `chatMessage`. `sent` is a
    comparison rather than a `term:value` pair, and uses `>=` and `<=` so a bound lands on the day
    the caller named. A query of nothing but punctuation contributes no term, so this string, not
    the arguments behind it, is the honest test of `is_empty`.
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
        # Microsoft's example is a user id "without '-'", which is exactly `UUID.hex`. Typing the
        # parameter as a UUID is also what makes this the one term that needs no quoting.
        terms.append(f"mentions:{criteria.mentions.hex}")
    if criteria.sent_after is not None:
        terms.append(f"sent>={criteria.sent_after.isoformat()}")
    if criteria.sent_before is not None:
        terms.append(f"sent<={criteria.sent_before.isoformat()}")
    if criteria.has_attachment is not None:
        terms.append(f"hasAttachment:{flag(criteria.has_attachment)}")
    if criteria.is_read is not None:
        terms.append(f"IsRead:{flag(criteria.is_read)}")
    if criteria.mentions_me is not None:
        terms.append(f"IsMentioned:{flag(criteria.mentions_me)}")
    return " ".join(terms)


async def teams_search_messages(
    client: GraphServiceClient, *, criteria: SearchCriteria, offset: int, size: int
) -> MessageSearchResults:
    """One page of matches for `criteria`. Exactly one Graph request, whatever the criteria."""
    query = _query_string(criteria)
    assert query, (
        "teams_search_messages needs at least one criterion; the tool refuses an empty set"
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
    with graph_errors(TOOL_NAME, step=STEP):
        response = await client.search.query.post(body)

    assert response is not None, "Graph answered POST /search/query with no response"
    container = _hits_container(response)
    hits = (container.hits or []) if container is not None else []
    more_to_come = bool(container.more_results_available) if container else False

    return MessageSearchResults(
        messages=[
            message for message in (MessageHit.from_hit(hit) for hit in hits) if message is not None
        ],
        # `moreResultsAvailable` alone is not a next page: a hitless page would hand back the offset
        # it was asked at, and a caller obeying `next_offset` would re-request it for ever.
        next_offset=offset + len(hits) if more_to_come and hits else None,
    )


def _hits_container(response: QueryPostResponse) -> SearchHitsContainer | None:
    """The one container this request produces. Graph "currently supports only a single
    searchRequest at a time" and one entity type, so the nesting holds one of each.
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
    # Closes over `transport` here; the default below holds this name, not a call (ruff's B008).
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    # Two steps rather than `@mcp.tool`, which hands back the function: `add_tool` returns the
    # registered tool, the only way to reach the schema `_require_a_criterion` adds to.
    @tool_metadata(
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
                    "Keywords to find. Every word must appear anywhere in any order; they are not "
                    + 'matched as phrases unless quoted. Quote terms for adjacency: `"release '
                    + 'notes"` matches only side by side, `release notes` matches anywhere. '
                    + "Search operators are searched as text, not interpreted. Use the other "
                    + "parameters for filtering."
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
                    "Only messages addressed to this person. Works only for one-to-one chats; "
                    + "hides group and channel matches."
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
            date | None,
            Field(
                description=(
                    "Only messages sent on or after this date (YYYY-MM-DD), inclusive. Applied "
                    + "by the index at no extra cost."
                )
            ),
        ] = None,
        sent_before: Annotated[
            date | None,
            Field(description="Only messages sent on or before this date (YYYY-MM-DD), inclusive."),
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
                    "How many results to skip. Start at 0; pass the previous response's "
                    + "`next_offset` to advance."
                ),
            ),
        ] = 0,
        size: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=("Results per page. Default 25, maximum " + f"{MAX_RESULTS}."),
            ),
        ] = 25,
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
        )

    _require_a_criterion(mcp.add_tool(search_teams_messages))


def _require_a_criterion(tool: Tool) -> None:
    """Put "at least one criterion" in the tool's schema, where a client can enforce it.

    A signature cannot say that optional parameters must not all be omitted, and FastMCP derives
    the schema from the signature. The runtime check stays: FastMCP validates arguments against the
    signature rather than against this schema, so a client that ignores it must still be refused.
    """
    tool.parameters["anyOf"] = [{"required": [name]} for name in CRITERIA]
