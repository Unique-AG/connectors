"""`search_messages` — full-text search across every Teams message the signed-in user can see.

`POST /search/query` with `entityTypes: ["chatMessage"]` is the only full-text path Microsoft
Graph offers over Teams messages, and it runs in delegated context only
(https://learn.microsoft.com/en-us/graph/search-concept-chat-messages). Four of its documented
properties shape everything below.

* **The hit is a projection, not a message.** The retrievable set is `channelIdentity`, `chatId`,
  `createdDateTime`, `etag`, `from`, `id`, `importance`, `lastModifiedDateTime`, `subject` and
  `webUrl` — no `body`. Graph says so outright: "The search Teams API doesn't return all
  properties defined in chatMessage." The only text a hit carries is the `summary` snippet. A
  result is therefore metadata plus a handle by necessity: the handle names the exact message
  Graph matched, which is the one thing about it a later answer can be lined up against.
* **`total` is not a match count.** "For Teams messages, the total property of the
  searchHitsContainer type contains the number of results on the page, not the total number of
  matching results." It is not read here and no total is reported: `moreResultsAvailable` is the
  only honest "keep going" signal Graph gives, and `next_offset` is how this tool says it.
* **Sorting is unsupported.** "The search API doesn't support custom sort for … chatMessage …", so
  there is no ordering knob to expose, and none is invented.
* **Paging is stateless.** `from`/`size` integers rather than an opaque `@odata.nextLink`, which is
  why `graph_client.collect_pages` has nothing to do here and why a caller can resume a search on
  a later, unrelated call.

Deliberately absent: the per-chat scan that the connector this one replaces falls back to when it
lacks a permission or is given a date filter. Graph caps reads at "one request per second per app
per tenant … on a given channel or chat" (https://learn.microsoft.com/en-us/graph/throttling), and
that budget is *per app*, so one user's sweep of fifty chats degrades every other user in the
tenant. Date bounds go into the query string instead, where the index applies them for the price of
the one request that was being made anyway. This tool is one Graph request, always.

**Two rules of the criteria are enforced twice, and the duplication is deliberate.** "At least one
criterion" is advertised in the input schema as an `anyOf` — the JSON Schema spelling of it, and the
only form a client can check — *and* re-checked in the tool body, because FastMCP validates
arguments against the function signature rather than against the schema it advertises, so a client
that ignores the `anyOf` would otherwise reach Graph with a search for everything. And whether the
criteria are empty is measured on the query string rather than on which arguments were passed, so a
`query` of nothing but punctuation is refused rather than sent.

What this file does not own is the handle grammar (`shared/handles.py`, so the handle minted here is
the handle a reader of one will parse — two spellers would look like a search result that cannot be
read) and the sender shape (`shared/messages.py`, so a hit and a read of the same message agree
about who sent it). Everything else — the name, the description, the arguments, the answer shape,
the request, the query builder, the injection guard and every refusal below — is here.
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

# `Chat.Read` is what `/search/query` accepts for the `chatMessage` entity; Graph's own search
# overview promises a search never returns more than the equivalent GET would, and every
# channel-message GET in v1.0 requires `ChannelMessage.Read.All` — so without it a search silently
# covers chats only. Both are requested rather than one, so a tenant that withholds the broad one
# is refused at consent time instead of being served half an answer at query time. The two names
# are `shared/handles.py`'s, because which of them a *read* is made under is decided by the surface
# a handle addresses; a search is made under both, having no handle yet.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

# Built once at import: a call inside a parameter default rebuilds the descriptor on every
# registration and is a lint error in both of this repo's checkers.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# Graph documents `size` as defaulting to 25 with a maximum of 1000, but the paragraph that caps a
# page at 25 names only the `message` and `event` entities, and no chatMessage-specific ceiling is
# published. 50 is the largest page this connector will claim on undocumented ground.
MAX_RESULTS = 50

_DESCRIPTION = f"""\
Search the Microsoft Teams messages the signed-in user can see — every one-to-one chat, group \
chat, meeting chat and channel they belong to — by keywords, sender, mentions, date, attachments \
and read state. Messages from ANY participant match, not only the user's own; call get_me if you \
need to know who the user is. It is the only tool here that searches.

A result is metadata plus a snippet, by necessity. Microsoft's search index answers with a reduced \
view of a message that contains no message body at all, so `summary` — Microsoft's own excerpt, \
truncated with `...` where it was cut — is the only text here. Every hit carries a `uri` handle \
naming that exact message, and no tool on this server takes one as an argument yet: it identifies \
a message rather than opening one, and there is no route from here to the full text. Never present \
`summary` as the whole message, and never conclude from it that the message does not say more.

There is no result total, and this is not an omission: Microsoft Graph reports a per-page count \
rather than a match count for Teams messages, so a total would be a fabrication. `next_offset` is \
the whole of the paging contract and the whole completeness signal: a value there means the index \
holds more matches, and null means this page is the last. Pass it back as `offset` to continue. A \
page can hold fewer than `size` messages: offsets index Graph's own results, and system messages \
("Ada joined the chat") are dropped from ours because Graph gives them neither an author nor any \
text.

The search covers every chat and channel the user belongs to and cannot be narrowed to one of \
them — Microsoft's index offers no such scope, so there is no chat or channel parameter and a \
`chat_id` from list_chats is not one. Narrow with `sender`, dates or more words instead, and read \
`chat_id` (or `team_id`/`channel_id`) on each hit to see where it came from.

Results cannot be sorted: Graph refuses sort options on a message search. Its documented default \
for message results is newest first and relevance can be mixed in, so compare `created_at` \
whenever order matters to the answer.

At least one criterion is required and all criteria given are ANDed. `query` is matched as plain \
words and every word must appear, anywhere in the message and in any order — the words do not have \
to be next to each other. To require that they are, quote them yourself: `"release notes"` matches \
only where those two words are adjacent. Search operators typed into `query` are searched for \
literally, so put a sender in `sender`, a date in `sent_after`/`sent_before`, and so on. Those two \
dates are inclusive whole days and are \
applied by the index itself, so a date-bounded search still costs one request and still covers \
channels. `recipient` is honoured by Microsoft only for one-to-one chats and will hide group and \
channel matches, so prefer `sender`. Channel matches need the delegated \
{CHANNEL_PERMISSION} permission, which this connector requires at sign-in rather \
than degrading to chats-only search without saying so.\
"""


class MessageHit(BaseModel):
    """One matched message: all Graph's search index will say about it, and how to name the rest."""

    uri: str | None = Field(
        description=(
            "A handle for this exact message, e.g. "
            + "`teams:///chats/{chatId}/messages/{messageId}` or "
            + "`teams:///teams/{teamId}/channels/{channelId}/messages/{messageId}`, with each id "
            + "percent-encoded. It names the message so that the same one can be recognised across "
            + "answers; no tool on this server takes it as an argument, so there is no route from "
            + "here to the message body and `summary` is the whole of the text. Null in the rare "
            + "case where Graph returned a hit with neither a chat nor a channel identity, which "
            + "cannot be addressed at all."
        )
    )
    message_id: str = Field(
        description=(
            "The message's Graph `id`. Unique only within its own chat, channel or reply thread — "
            + "Microsoft documents that the same id may recur elsewhere — so identify a message by "
            + "`uri`, never by this alone."
        )
    )
    chat_id: str | None = Field(
        description=(
            "The chat this message is in, unencoded, e.g. `19:...@thread.v2`. It is the same id "
            + "list_chats reports as `chat_id`, which is how to put a topic and members to the "
            + "chat a hit came from. Null for a channel message; `team_id` and `channel_id` are "
            + "set instead."
        )
    )
    team_id: str | None = Field(
        description="The team a channel message belongs to. Null for a chat message."
    )
    channel_id: str | None = Field(
        description="The channel a channel message was posted in. Null for a chat message."
    )
    subject: str | None = Field(
        description=(
            "The message subject. Usually null or empty: Teams only sets one on some channel root "
            + "posts, never on ordinary chat messages."
        )
    )
    summary: str | None = Field(
        description=(
            "Microsoft's own snippet of the matching text, truncated with `...` where it was cut. "
            + "This is the ONLY message content this search returns — Graph's search projection "
            + "has no body — so do not quote it as the whole message or infer from its absence."
        )
    )
    sender: MessageSender = Field(description="Who sent the message.")
    created_at: datetime | None = Field(
        description=(
            "When the message was sent. Compare this when order matters: Graph refuses to sort a "
            + "message search, so the sequence results arrive in is not a contract."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When the message was last modified. Microsoft counts adding or removing a reaction "
            + "as a modification, so a difference from `created_at` is not evidence of an edit — "
            + "the property behind Teams' own 'Edited' flag is a different one, and Microsoft's "
            + "search index does not return it."
        )
    )
    importance: str | None = Field(
        description="`normal`, `high` or `urgent`, as the sender marked the message."
    )
    web_url: str | None = Field(
        description=(
            "A link that opens the message in Microsoft Teams. Populated for channel messages and "
            + "null for chat messages, which Graph gives no such link."
        )
    )


class MessageSearchResults(BaseModel):
    messages: list[MessageHit] = Field(description="The matching messages on this page of results.")
    next_offset: int | None = Field(
        description=(
            "The `offset` that reaches the next page of matches, or null when this page is the "
            + "last. It is both how to page on and the whole completeness signal: a value here "
            + "means Microsoft's index holds more matches than this page, and null means it does "
            + "not. Graph reports no match total for Teams messages, so there is no other. It "
            + "counts the hits Graph returned rather than the messages listed here, because "
            + "offsets index Graph's own unfiltered results."
        )
    )


@dataclass(frozen=True, slots=True)
class SearchCriteria:
    """What to match, before it becomes a query string.

    Every field is optional and Microsoft ANDs them together. All of them unset would ask for
    every message the user can see, which is not a question anyone asked — `is_empty` is what the
    tool boundary refuses.
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


# The criteria a caller may set, in declaration order. The tool advertises this as a JSON Schema
# `anyOf` of one-element `required` lists, which is how "at least one of these" becomes something
# a client can check rather than a sentence in a description it may not read.
CRITERIA: tuple[str, ...] = tuple(field.name for field in fields(SearchCriteria))

# What the tool says when it is called with nothing to look for. Graph would answer such a request
# with an arbitrary slice of everything the user can read, which reads like a real result set and
# is the one failure mode a model cannot detect from the response. Built from `CRITERIA` rather
# than written out, so a criterion added above appears here without anybody remembering to add it.
_NO_CRITERIA = (
    "search_messages needs at least one of "
    + ", ".join(CRITERIA)
    + ". Searching with none of them would return an arbitrary sample of every message the user "
    + "can see, not an answer. Add the keywords, person or date range the question is about."
)

# The characters that would let a value be read as Keyword Query Language instead of as text:
# whitespace separates terms, `:` `<` `>` `=` introduce a property restriction or a comparison,
# `(` and `)` group, and `"` would close the quoting applied here. A value holding any of them is
# quoted — which is what turns `sent>2020-01-01` into something to look for rather than a filter
# the caller was never offered. A value holding none of them cannot express a restriction, so it is
# left alone and stays a keyword. This is the guard `services/teams-mcp` ships merged, and it is
# for a *filter value* — one scope term's argument, e.g. the `from:` in `from:"ada lovelace"`.
_KQL_OPERATORS = re.compile(r'[\s:"<>=()]')


def _quoted(value: str) -> str:
    """A filter value, safe to put after a scope term. One value, therefore at most one term."""
    if _KQL_OPERATORS.search(value) is None:
        return value
    return _phrase(value)


# A caller's free text is not a filter value, and quoting it like one costs them every match whose
# words are not adjacent — Microsoft is explicit about both halves of this
# (https://learn.microsoft.com/en-us/sharepoint/dev/general-development/keyword-query-language-kql-syntax-reference):
# a quoted phrase "returns only the items in which the words in your phrase are located next to each
# other", while "if there are multiple free-text expressions without any operators in between them,
# the query behavior is the same as using the AND operator". So free text is guarded one word at a
# time and the words reach Graph as separate terms it will AND — every word must appear, anywhere in
# the message, in any order. Adjacency is still available: a caller who wants it quotes the words
# themselves, and this is what tells those two apart.
_PHRASE = re.compile(r'"([^"]*)"')

# Beyond the operator characters above, a *word* has two further ways to be read as KQL. `*` is the
# wildcard, and KQL's boolean and proximity operators are themselves words — "the operators are
# case-sensitive (uppercase)", which is why the comparison below is too. Neither can smuggle in a
# scope term, but both change what the search *means* rather than what it looks for: a bare `OR`
# between two of the caller's words turns the AND they were promised into an OR. `-` is KQL's
# documented shorthand for NOT and negates the word it precedes. (`+` is the shorthand for AND,
# which is the default anyway, so it needs no handling.) All of these are quoted into literal text,
# so every word of the query is looked for and none of it is obeyed.
_KQL_WILDCARD = "*"
_KQL_KEYWORDS = frozenset({"AND", "OR", "NOT", "NEAR", "ONEAR"})


def _free_text(query: str) -> str:
    """A caller's own words, as terms Graph will AND. Empty when they typed nothing to look for.

    Whatever the caller put in double quotes stays one phrase — the only adjacency this tool asks
    Graph for, because it is the only one anybody asked for. Everything outside those quotes is
    words, and an unbalanced quote is just a character in one of them.
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
    """The words of `text`, each one safe to hand to Graph as a term of its own."""
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
    """`text` as a KQL phrase: matched where those words are adjacent, and read as no operator.

    The quoting is the guard as much as it is the phrase — everything inside a quoted phrase is
    text — so the only thing left to handle is a quote in the text itself, which KQL escapes by
    doubling it. That keeps the number of quotes in the query even, and so keeps the quoting
    unclosable from inside.
    """
    return '"' + text.replace('"', '""') + '"'


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _query_string(criteria: SearchCriteria) -> str:
    """The `queryString` these criteria become. Empty exactly when nothing was asked for.

    The scope terms are the ones Microsoft documents for `chatMessage`: `from`, `to`,
    `hasAttachment`, `IsRead`, `IsMentioned`, `mentions` and `sent`, in their documented spellings
    (the casing is Microsoft's, not a mistake). `sent` is the one that is not a `term:value` pair
    at all — it is a comparison, `sent > 2022-07-14` — and `>=`/`<=` are used so that a bound
    lands on the day the caller named rather than the day after it, which is what `sent_after` and
    `sent_before` promise.

    `query` is the one input that is not a scope term's value, and it is the one that becomes more
    than one term: it is free text, so it becomes the caller's words, ANDed with everything else
    here. A query of nothing but punctuation therefore contributes nothing, which is what makes
    this string — rather than the arguments it was built from — the honest test of `is_empty`.
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
        # Microsoft's example is a user id "without '-'", which is exactly `UUID.hex`. Typing the
        # parameter as a UUID is also what makes this the one term needing no quoting.
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
    """One page of matches for `criteria`, starting at `offset`.

    Exactly one Graph request, whatever the criteria: there is no fan-out and no second call to
    fill in content.
    """
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
    """The one container this request can produce.

    Graph "currently supports only a single searchRequest at a time" and one entity type, so the
    nesting — a response per request, a container per entity type — only ever holds one of each.
    """
    for search_response in response.value or []:
        for container in search_response.hits_containers or []:
            return container
    return None


def _message(hit: SearchHit) -> MessageHit | None:
    """One hit as a result, or None for a hit that is not a message a person wrote."""
    resource = hit.resource
    if not isinstance(resource, ChatMessage) or resource.id is None:
        return None
    sender = sender_of(resource.from_)
    if sender is None:
        # A system event message — "Ada joined the chat", a call ending, a channel being renamed.
        # Graph sends `from: null` and a body of the literal `<systemEventMessage/>` for these,
        # and the human-readable sentence Teams shows is rendered by the client and never sent, so
        # such a hit has neither an author nor any text. The `messageType` and `eventDetail`
        # properties that would name it are not in search's retrievable set, which leaves the
        # missing author as the signal — and it is the one Microsoft's own examples show.
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
        # `ChatMessageImportance` subclasses `str`, so the member is its own wire value.
        importance=resource.importance,
        web_url=resource.web_url,
    )


def _hit_uri(
    *, message_id: str, chat_id: str | None, team_id: str | None, channel_id: str | None
) -> str | None:
    """This hit's handle, or None for a hit Graph gave nothing addressable."""
    if team_id is not None and channel_id is not None:
        return MessageHandle(message_id=message_id, team_id=team_id, channel_id=channel_id).uri
    if chat_id is not None:
        return MessageHandle(message_id=message_id, chat_id=chat_id).uri
    return None


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this tool against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tool
    borrows it per call and never owns it. `create_app` closes it on shutdown.
    """

    # Declared and registered in two steps rather than with `@mcp.tool`, which does both and hands
    # back the function: `add_tool` returns the registered tool, which is the only way to reach the
    # schema `_require_a_criterion` has to add to. Same registration, same metadata.
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
                    "Keywords to find in the message text or in an attachment's contents. Every "
                    + "word must appear, anywhere in the message and in any order; they are not "
                    + "matched as a phrase unless you quote them, so `release notes` finds "
                    + 'messages containing both words and `"release notes"` only messages where '
                    + "they are adjacent. Never a query language — a search operator written here "
                    + "is searched for as literal text, so use the other parameters for filters."
                ),
            ),
        ] = None,
        sender: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only messages from this person, by name, alias or email address. Prefer this "
                    + "over naming the person in `query`, which would match messages that merely "
                    + "mention them."
                ),
            ),
        ] = None,
        recipient: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only messages addressed to this person. Microsoft supports this only "
                    + "partially, for one-to-one chats, so it hides group-chat and channel "
                    + "matches: an empty result here is not evidence that no such message exists."
                ),
            ),
        ] = None,
        mentions: Annotated[
            UUID | None,
            Field(
                description=(
                    "Only messages that @-mention this user, by Microsoft Entra object id (the "
                    + "`user_id` of a sender here, or from get_me). A name will not work: "
                    + "Microsoft matches this term on the id alone."
                )
            ),
        ] = None,
        sent_after: Annotated[
            date | None,
            Field(
                description=(
                    "Only messages sent on or after this date (YYYY-MM-DD), inclusive. Applied by "
                    + "Microsoft's index, so it costs nothing extra and narrows chats and "
                    + "channels alike."
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
                    "True for only messages carrying an attachment, false for only messages "
                    + "without one. Omit to search both."
                )
            ),
        ] = None,
        is_read: Annotated[
            bool | None,
            Field(
                description=(
                    "True for only messages the signed-in user has read, false for only unread "
                    + "ones. Omit to search both."
                )
            ),
        ] = None,
        mentions_me: Annotated[
            bool | None,
            Field(
                description=(
                    "True for only messages that @-mention the signed-in user, false for only "
                    + "messages that do not. Omit to search both."
                )
            ),
        ] = None,
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "How many results to skip. Start at 0 and pass the previous response's "
                    + "`next_offset` to advance; it is an index into Microsoft's results, not "
                    + "into the messages this tool returned."
                ),
            ),
        ] = 0,
        size: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=(
                    "How many results to ask Microsoft for. Default 25, maximum "
                    + f"{MAX_RESULTS} — Microsoft documents no page size above "
                    + "that for message search."
                ),
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
    """Put "at least one criterion" in the tool's schema, where a client can enforce it.

    FastMCP derives an input schema from the function signature, and a signature has no way to say
    that a set of optional parameters cannot all be omitted — so the rule would otherwise live only
    in the description and in the tool's own runtime check. `anyOf` over one-element `required`
    lists is the JSON Schema spelling of it, and the registered tool's schema is where it goes.
    The runtime check stays: FastMCP validates arguments against the signature rather than against
    this schema, so a client that ignores it must still be refused.
    """
    tool.parameters["anyOf"] = [{"required": [name]} for name in CRITERIA]
