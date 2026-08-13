"""Full-text search across the Microsoft Teams messages the signed-in user can see.

`POST /search/query` with `entityTypes: ["chatMessage"]` is the only full-text path Microsoft
Graph offers over Teams messages, and it runs in delegated context only
(https://learn.microsoft.com/en-us/graph/search-concept-chat-messages). Four of its documented
properties shape everything below.

* **The hit is a projection, not a message.** The retrievable set is `channelIdentity`, `chatId`,
  `createdDateTime`, `etag`, `from`, `id`, `importance`, `lastModifiedDateTime`, `subject` and
  `webUrl` — no `body`. Graph says so outright: "The search Teams API doesn't return all
  properties defined in chatMessage." The only text a hit carries is the `summary` snippet. A
  result is therefore metadata plus a handle by necessity, and the handle is what a reader tool
  resolves into the message itself.
* **`total` is not a match count.** "For Teams messages, the total property of the
  searchHitsContainer type contains the number of results on the page, not the total number of
  matching results." It is not read here and no total is reported: `moreResultsAvailable` is the
  only honest "keep going" signal Graph gives.
* **Sorting is unsupported.** "The search API doesn't support custom sort for … chatMessage …", so
  there is no ordering knob to expose, and none is invented.
* **Paging is stateless.** `from`/`size` integers rather than an opaque `@odata.nextLink`, which is
  why `graph_client.collect_pages` has nothing to do here and why a caller can resume a search on
  a later, unrelated call.

Deliberately absent: the per-chat scan that the connector this one replaces falls back to when it
lacks a permission or is given a date filter. Graph caps reads at "one request per second per app
per tenant … on a given channel or chat" (https://learn.microsoft.com/en-us/graph/throttling), and
that budget is *per app*, so one user's sweep of fifty chats degrades every other user in the
tenant. Date bounds go into the query string instead, where the index applies them for the price
of the one request that was being made anyway.
"""

import re
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import cast
from urllib.parse import quote
from uuid import UUID

from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.chat_message_from_identity_set import ChatMessageFromIdentitySet
from msgraph.generated.models.entity_type import EntityType
from msgraph.generated.models.search_hit import SearchHit
from msgraph.generated.models.search_hits_container import SearchHitsContainer
from msgraph.generated.models.search_query import SearchQuery
from msgraph.generated.models.search_request import SearchRequest
from msgraph.generated.search.query.query_post_request_body import QueryPostRequestBody
from msgraph.generated.search.query.query_post_response import QueryPostResponse
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import graph_errors

# `Chat.Read` is what `/search/query` accepts for the `chatMessage` entity; Graph's own search
# overview promises a search never returns more than the equivalent GET would, and every
# channel-message GET in v1.0 requires `ChannelMessage.Read.All` — so without it a search silently
# covers chats only. Both are requested rather than one, so a tenant that withholds the broad one
# is refused at consent time instead of being served half an answer at query time. The broad one is
# named separately because the tool's description has to tell a model what channel coverage costs.
CHANNEL_PERMISSION = "ChannelMessage.Read.All"
GRAPH_PERMISSIONS: tuple[str, ...] = ("Chat.Read", CHANNEL_PERMISSION)

# Graph documents `size` as defaulting to 25 with a maximum of 1000, but the paragraph that caps a
# page at 25 names only the `message` and `event` entities, and no chatMessage-specific ceiling is
# published. 50 is the largest page this connector will claim on undocumented ground.
MAX_RESULTS = 50


class MessageSender(BaseModel):
    """Who sent a matched message, from whichever identity shape Graph used.

    Two shapes, because Teams messages are indexed out of the substrate mailbox: a search hit
    carries an Exchange-style `emailAddress` (a name and an address), while every Teams read API
    returns a `teamworkUserIdentity` (an id and an optional display name, and no email at all).
    Which fields are populated therefore says which shape Graph answered with, and a null is not
    evidence that the sender has no name or no address.
    """

    display_name: str | None = Field(
        description=(
            "The sender's name as Teams shows it. Microsoft documents this as optional and it is "
            + "genuinely absent on some messages, including messages from external and federated "
            + "users — a null is not an anonymous sender."
        )
    )
    email: str | None = Field(
        description=(
            "The sender's email address. Present when Graph answered with the mailbox-shaped "
            + "identity that search hits normally carry, and null otherwise; the Teams identity "
            + "has no email property at all, so compare `user_id` when this is null."
        )
    )
    user_id: str | None = Field(
        description=(
            "The sender's Microsoft Entra object id, when Graph answered with the Teams-shaped "
            + "identity. This is the value the `mentions` search parameter takes, and the only "
            + "sender field safe to compare against ids from other tools. Null for a message sent "
            + "by an application (a bot or a connector), and null when Graph gave an email "
            + "address instead."
        )
    )


class MessageHit(BaseModel):
    """One matched message: all Graph's search index will say about it, and how to read the rest."""

    uri: str | None = Field(
        description=(
            "A handle for this exact message, e.g. "
            + "`teams:///chats/{chatId}/messages/{messageId}` or "
            + "`teams:///teams/{teamId}/channels/{channelId}/messages/{messageId}`, with each id "
            + "percent-encoded. Pass it verbatim to a tool that reads a message resource; this "
            + "search returns no message body, so it is the only route to the full text, the "
            + "attachments and the mentions. Null in the rare case where Graph returned a hit "
            + "with neither a chat nor a channel identity, which cannot be addressed."
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
            "The chat this message is in, unencoded, e.g. `19:...@thread.v2`. Null for a channel "
            + "message; `team_id` and `channel_id` are set instead."
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
            + "has no body — so do not quote it as the whole message or infer from its absence. "
            + "Read `uri` for the real text."
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
            + "as a modification, so a difference from `created_at` is not evidence of an edit."
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


class MessageSearchResults(BaseModel):
    messages: list[MessageHit] = Field(description="The matching messages on this page of results.")
    more_results_available: bool = Field(
        description=(
            "Whether Microsoft's index has further matches beyond this page. This is the only "
            + "signal Graph gives: it reports no match total for Teams messages, so neither does "
            + "this tool."
        )
    )
    next_offset: int | None = Field(
        description=(
            "The `offset` that reaches the next page, or null when there is none. It counts the "
            + "hits Graph returned rather than the messages listed here, because offsets index "
            + "Graph's own unfiltered results."
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
    fill in content. Callers that want the text of a match read its `uri`.
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
    more_results_available = bool(container.more_results_available) if container else False

    return MessageSearchResults(
        messages=[message for message in (_message(hit) for hit in hits) if message is not None],
        more_results_available=more_results_available,
        next_offset=offset + len(hits) if more_results_available else None,
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
    sender = _sender(resource.from_)
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
        uri=_uri(
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


def _uri(
    *, message_id: str, chat_id: str | None, team_id: str | None, channel_id: str | None
) -> str | None:
    """The handle a reader resolves back into this message.

    Ids are percent-encoded because Teams ids are full of `:`, `@` and `/`-adjacent characters
    (`19:...@thread.v2`), and a handle that has to be parsed back apart cannot afford ambiguity.
    """
    if team_id is not None and channel_id is not None:
        return (
            f"teams:///teams/{_segment(team_id)}/channels/{_segment(channel_id)}"
            + f"/messages/{_segment(message_id)}"
        )
    if chat_id is not None:
        return f"teams:///chats/{_segment(chat_id)}/messages/{_segment(message_id)}"
    return None


def _segment(value: str) -> str:
    return quote(value, safe="")


def _sender(identity: ChatMessageFromIdentitySet | None) -> MessageSender | None:
    """The sender, or None when the identity set names nobody at all."""
    if identity is None:
        return None
    mailbox_name, mailbox_address = _mailbox_identity(identity)
    user = identity.user
    application = identity.application
    display_name = user.display_name if user is not None else None
    if display_name is None and application is not None:
        display_name = application.display_name
    sender = MessageSender(
        display_name=display_name or mailbox_name,
        email=mailbox_address,
        user_id=user.id if user is not None else None,
    )
    if (sender.display_name, sender.email, sender.user_id) == (None, None, None):
        return None
    return sender


def _mailbox_identity(identity: ChatMessageFromIdentitySet) -> tuple[str | None, str | None]:
    """The `emailAddress` a search hit carries instead of a Teams identity, as (name, address).

    Search reads Teams messages out of the substrate mailbox, so `POST /search/query` answers with
    `from: {"emailAddress": {"name": ..., "address": ...}}` where the Teams APIs answer with
    `from: {"user": {...}}`. The SDK's identity set has no field for the mailbox shape, so it
    arrives in `additional_data` — untyped by construction, hence the narrowing here.
    """
    extra = cast("dict[str, object]", identity.additional_data)
    mailbox = extra.get("emailAddress")
    if not isinstance(mailbox, dict):
        return (None, None)
    fields_ = cast("dict[str, object]", mailbox)
    return (_string(fields_.get("name")), _string(fields_.get("address")))


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None
