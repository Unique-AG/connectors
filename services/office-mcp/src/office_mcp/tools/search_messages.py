"""`search_messages` — full-text search across every Teams message the signed-in user can see.

`POST /search/query` with `entityTypes: ["chatMessage"]` is the only full-text path Graph offers
over Teams messages and runs in delegated context only. Four Graph properties shape this tool:

* The hit is a projection with no body. Graph says so: "The search Teams API doesn't return all
  properties defined in chatMessage." Only the `summary` snippet carries text. A result is metadata
  plus a handle, and `read_message` resolves the handle into the full message.
* `total` is not a match count. "For Teams messages, the total property contains the number of
  results on the page, not the total number of matching results." `moreResultsAvailable` is the
  only "keep going" signal. `next_offset` is how this tool says it.
* Sorting is unsupported. "The search API doesn't support custom sort for … chatMessage …". No
  ordering is exposed.
* Paging is stateless. `from`/`size` integers rather than `@odata.nextLink`. A caller can resume
  a search on a later, unrelated call.

This tool makes one Graph request with no fan-out. No per-chat scans. Graph caps reads at "one
request per second per app per tenant … on a given channel or chat". One user's sweep of fifty
chats degrades every other user. Date bounds go into the query string, where the index applies them
at no extra cost.

"At least one criterion" is enforced twice. The input schema declares it as an `anyOf`, and the
tool body re-checks it. FastMCP validates the signature, not the schema, so a client ignoring the
`anyOf` would otherwise reach Graph with an unrestricted search. Emptiness is measured on the query
string, not on which arguments were passed.
"""

import re
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Annotated
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

from office_mcp.graph_client import graph_client_for, graph_errors
from office_mcp.shared.handles import CHANNEL_PERMISSION, CHAT_PERMISSION, MessageHandle
from office_mcp.shared.messages import MessageSender, sender_of
from office_mcp.shared.seam import READ_ONLY, graph_token, graph_tool_errors

TOOL_NAME = "search_messages"

# Chat.Read searches chats only. To include channels, ChannelMessage.Read.All is needed.
# Both permissions are requested so a tenant that withholds the broad one is refused at consent
# time rather than served half an answer at query time.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# Graph caps message and event at 25. This tool uses 50 as a safe intermediate.
MAX_RESULTS = 50

_DESCRIPTION = f"""\
Search Microsoft Teams messages the signed-in user can see in chats and channels by keywords, \
sender, mentions, date, attachments, and read state. Messages from any participant match. Call \
get_me to learn who the user is. This is the only search tool here.

A result is metadata plus a snippet, by necessity. Graph's search index has no message body, so \
`summary` — Microsoft's excerpt, truncated with `...` — is the only text here. Every hit carries \
a `uri` handle. Pass it to read_message for the full text, attachments and mentions. Never present \
`summary` as the whole message or conclude from it that more text exists.

Graph gives a per-page count, not a match total. Use `next_offset` to page. A value means more \
matches exist. Null means no more pages. System messages like "Ada joined" are dropped — a system \
event has no `sender` (Graph sends `from: null`) and `body.content` is `<systemEventMessage/>`; \
the Teams client renders the sentence, not Graph.

Search covers all user chats and channels. You cannot narrow to one. Use `sender`, dates or more \
words to filter. Read `chat_id` or `channel_id` on each hit to see where it came from.

Results are not sorted. Graph refuses sort options. The default is newest first with possible \
relevance mixing. Compare `created_at` when order matters.

At least one criterion is required. All criteria are ANDed. `query` matches as plain words: every \
word must appear anywhere, in any order. Quote to require adjacency: `"release notes"` matches \
only side by side. Search operators in `query` are treated as text. Put operators in their own \
parameters. Note: `query` matches @-mentions and message text equally; use the `mentions` \
parameter to search mentions exclusively. Dates are inclusive whole days, applied by the index \
at no cost, and cover both chats and channels. `recipient` works only for one-to-one chats; \
prefer `sender`. Channel search requires the delegated {CHANNEL_PERMISSION} permission, which \
this connector requires at sign-in.\
"""


class MessageHit(BaseModel):
    """One matched message: all Graph's search index returns and how to read the rest."""

    uri: str | None = Field(
        description=(
            "A handle to read this message: `teams:///chats/{chatId}/messages/{messageId}` or "
            + "`teams:///teams/{teamId}/channels/{channelId}/messages/{messageId}` with ids "
            + "percent-encoded. Pass it verbatim to read_message. Search has no message body, so "
            + "this is the only route to full text, attachments and mentions. Null when Graph "
            + "returned a hit with neither chat nor channel identity."
        )
    )
    message_id: str = Field(
        description=(
            "Graph message `id`. Unique within its chat or channel only. Use `uri` globally."
        )
    )
    chat_id: str | None = Field(
        description=(
            "The chat this message is in, e.g. `19:...@thread.v2`. Null for channel messages."
        )
    )
    team_id: str | None = Field(description="The team, for a channel message. Null for chats.")
    channel_id: str | None = Field(
        description="The channel, for a channel message. Null for chats."
    )
    subject: str | None = Field(
        description="Message subject. Usually null: Teams sets it only on some channel root posts."
    )
    summary: str | None = Field(
        description=(
            "Microsoft's excerpt, truncated with `...`. This is the ONLY message text in search "
            + "results — Graph has no body. Do not quote as the whole message or infer from its "
            + "absence. Read `uri` for the real text."
        )
    )
    sender: MessageSender = Field(description="Who sent the message.")
    created_at: datetime | None = Field(
        description="When sent. Compare to order results: Graph does not sort message search."
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When last modified. Microsoft counts reaction add/remove as modification. A "
            + "difference from `created_at` is not proof of edit. Read_message reports "
            + "`last_edited_at`, which is Teams' 'Edited' flag."
        )
    )
    importance: str | None = Field(description="`normal`, `high` or `urgent`, as marked by sender.")
    web_url: str | None = Field(
        description=(
            "A link to open the message in Microsoft Teams. Set for channels only. Null for chats."
        )
    )


class MessageSearchResults(BaseModel):
    messages: list[MessageHit] = Field(description="Matching messages on this page.")
    next_offset: int | None = Field(
        description=(
            "The offset for the next page, or null when no more pages exist. Null means either no "
            + "more results, or this page had no hits to advance from even though more may exist — "
            + "do not use this offset again. It counts Graph's hits, not returned messages, "
            + "because offsets index Graph's unfiltered results."
        )
    )


@dataclass(frozen=True, slots=True)
class SearchCriteria:
    """What to match, before becoming a query string.

    Every field is optional. Microsoft ANDs them. All unset asks for every message the user can
    see. `is_empty` is what the tool boundary refuses.
    """

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
        """Whether these criteria would match on nothing at all."""
        return not _query_string(self)


CRITERIA: tuple[str, ...] = tuple(field.name for field in fields(SearchCriteria))

# Built from `CRITERIA` so any added criterion appears here automatically.
_NO_CRITERIA = (
    "search_messages needs at least one of "
    + ", ".join(CRITERIA)
    + ". No criteria returns an arbitrary sample of all messages the user can see. Add keywords, "
    + "a person or a date range."
)

# Guard for filter values (scope term arguments like `from:"ada lovelace"`). Prevent KQL parsing.
_KQL_OPERATORS = re.compile(r'[\s:"<>=()]')


def _quoted(value: str) -> str:
    """A filter value safe after a scope term. At most one term."""
    if _KQL_OPERATORS.search(value) is None:
        return value
    return _phrase(value)


# Free text is guarded one word at a time so words reach Graph as separate AND terms. A caller
# who wants adjacency quotes the words themselves.
_PHRASE = re.compile(r'"([^"]*)"')

# Wildcard and boolean/proximity operators (case-sensitive, uppercase). Quote them to make them
# literal text so they are looked for, not obeyed.
_KQL_WILDCARD = "*"
_KQL_KEYWORDS = frozenset({"AND", "OR", "NOT", "NEAR", "ONEAR"})


def _free_text(query: str) -> str:
    """A caller's words as terms Graph will AND. Empty when they typed nothing.

    Double-quoted text stays one phrase — the only adjacency requested. Everything outside quotes
    becomes words. An unbalanced quote is just a character.
    """
    terms: list[str] = []
    words_from = 0
    for phrase in _PHRASE.finditer(query):
        terms.extend(_keywords(query[words_from : phrase.start()]))
        quoted = phrase.group(1).strip()
        if quoted:
            terms.append(_phrase(quoted))
        words_from = phrase.end()
    terms.extend(_keywords(query[words_from:]))
    return " ".join(terms)


def _keywords(text: str) -> list[str]:
    """The words of `text`, each safe as a term."""
    return [_keyword(word) for word in text.split()]


def _keyword(word: str) -> str:
    if (
        _KQL_OPERATORS.search(word) is not None
        or _KQL_WILDCARD in word
        or word.startswith("-")
        or word in _KQL_KEYWORDS
    ):
        return _phrase(word)
    return word


def _phrase(text: str) -> str:
    """`text` as a KQL phrase: adjacent words, read as no operator.

    Doubling internal quotes keeps the quoting unclosable from inside.
    """
    return '"' + text.replace('"', '""') + '"'


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _query_string(criteria: SearchCriteria) -> str:
    """The `queryString` these criteria make. Empty exactly when nothing was asked for.

    Scope terms use Microsoft's documented spellings and casing: `from`, `to`, `hasAttachment`,
    `IsRead`, `IsMentioned`, `mentions`, `sent`. The `query` input becomes multiple terms (caller's
    words ANDed together). A query of only punctuation contributes nothing, so measure emptiness on
    the string, not on which arguments were passed.
    """
    terms: list[str] = []
    if criteria.query:
        free_text = _free_text(criteria.query)
        if free_text:
            terms.append(free_text)
    if criteria.sender:
        terms.append(f"from:{_quoted(criteria.sender)}")
    if criteria.recipient:
        terms.append(f"to:{_quoted(criteria.recipient)}")
    if criteria.mentions is not None:
        # Microsoft matches on the id alone. UUID.hex is the id "without '-'".
        terms.append(f"mentions:{criteria.mentions.hex}")
    if criteria.sent_after is not None:
        terms.append(f"sent>={criteria.sent_after.isoformat()}")
    if criteria.sent_before is not None:
        terms.append(f"sent<={criteria.sent_before.isoformat()}")
    if criteria.has_attachment is not None:
        terms.append(f"hasAttachment:{_flag(criteria.has_attachment)}")
    if criteria.is_read is not None:
        terms.append(f"IsRead:{_flag(criteria.is_read)}")
    if criteria.mentions_me is not None:
        terms.append(f"IsMentioned:{_flag(criteria.mentions_me)}")
    return " ".join(terms)


async def search_messages(
    client: GraphServiceClient, *, criteria: SearchCriteria, offset: int, size: int
) -> MessageSearchResults:
    """One page of matches for `criteria`, starting at `offset`. One Graph request."""
    query = _query_string(criteria)
    assert query, "search_messages needs at least one criterion; the tool refuses an empty set"
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
    with graph_errors():
        response = await client.search.query.post(body)

    assert response is not None, "Graph answered POST /search/query with no response"
    container = _hits_container(response)
    hits = (container.hits or []) if container is not None else []
    more_to_come = bool(container.more_results_available) if container else False

    return MessageSearchResults(
        messages=[message for message in (_message(hit) for hit in hits) if message is not None],
        # `moreResultsAvailable` on its own is not a next page. The offset advances by the hits
        # Graph returned, so a page carrying none of them while still saying more are coming would
        # hand back the very offset it was asked at — and a caller doing what `next_offset`
        # promises re-requests that same empty page for ever. There is no offset that reaches
        # anything further from here, and null is how this contract says so.
        next_offset=offset + len(hits) if more_to_come and hits else None,
    )


def _hits_container(response: QueryPostResponse) -> SearchHitsContainer | None:
    """The one container Graph returns. Graph supports one searchRequest at a time."""
    for search_response in response.value or []:
        for container in search_response.hits_containers or []:
            return container
    return None


def _message(hit: SearchHit) -> MessageHit | None:
    """One hit as a result, or None for a message a person did not write.

    System event messages carry `from: null` (no sender), so recognizing them
    here prevents them from entering results.
    """
    resource = hit.resource
    if not isinstance(resource, ChatMessage) or resource.id is None:
        return None
    sender = sender_of(resource.from_)
    if sender is None:
        # System event messages have no author. Drop them.
        return None
    channel = resource.channel_identity
    team_id = channel.team_id if channel is not None else None
    channel_id = channel.channel_id if channel is not None else None
    return MessageHit(
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
        importance=resource.importance,
        web_url=resource.web_url,
    )


def _hit_uri(
    *, message_id: str, chat_id: str | None, team_id: str | None, channel_id: str | None
) -> str | None:
    """This hit's handle, or None if Graph gave no addressable surface."""
    if team_id is not None and channel_id is not None:
        return MessageHandle(message_id=message_id, team_id=team_id, channel_id=channel_id).uri
    if chat_id is not None:
        return MessageHandle(message_id=message_id, chat_id=chat_id).uri
    return None


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Register this tool against the shared Graph transport."""

    # Register in two steps so add_tool returns the tool object for schema modification.
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
                    "Keywords to find. Every word must appear anywhere, in any order; they are not "
                    + 'matched as phrases unless quoted. Quote for adjacency: `"release notes"` '
                    + "matches side by side only. Search operators are treated as text. Use other "
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
                    + "naming them in `query`."
                ),
            ),
        ] = None,
        recipient: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Only messages to this person. Works only in one-to-one chats.",
            ),
        ] = None,
        mentions: Annotated[
            UUID | None,
            Field(
                description=(
                    "Only messages that @-mention this user, by Entra object id. Names do not "
                    + "work; Microsoft matches the id only. Use this parameter instead of `query` "
                    + "to search mentions exclusively; `query` also matches the name in message "
                    + "text."
                )
            ),
        ] = None,
        sent_after: Annotated[
            date | None,
            Field(description="Only messages sent on or after this date (YYYY-MM-DD), inclusive."),
        ] = None,
        sent_before: Annotated[
            date | None,
            Field(description="Only messages sent on or before this date (YYYY-MM-DD), inclusive."),
        ] = None,
        has_attachment: Annotated[
            bool | None,
            Field(description="True: with attachments. False: without. Omit to search both."),
        ] = None,
        is_read: Annotated[
            bool | None,
            Field(description="True: read by user. False: unread. Omit to search both."),
        ] = None,
        mentions_me: Annotated[
            bool | None,
            Field(description="True: @-mentions user. False: does not. Omit to search both."),
        ] = None,
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "How many results to skip. Start at 0; pass the previous `next_offset` to "
                    + "advance."
                ),
            ),
        ] = 0,
        size: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=f"Results per page. Default 25, maximum {MAX_RESULTS}.",
            ),
        ] = 25,
        graph_token: str = _TOKEN,
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
        with graph_tool_errors(*GRAPH_PERMISSIONS):
            return await search_messages(
                graph_client_for(transport, graph_token),
                criteria=criteria,
                offset=offset,
                size=size,
            )

    _require_a_criterion(mcp.add_tool(search_teams_messages))


def _require_a_criterion(tool: Tool) -> None:
    """Put "at least one criterion" in the tool's schema for client-side enforcement.

    FastMCP signatures cannot express that optional parameters cannot all be omitted. JSON Schema
    can, via `anyOf` with `required` lists. The runtime check still guards: FastMCP validates
    signatures, not schemas, so a client ignoring the schema must still be refused.
    """
    tool.parameters["anyOf"] = [{"required": [name]} for name in CRITERIA]
