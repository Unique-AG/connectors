"""`outlook_search_mail` — find a message anywhere in the signed-in user's mailbox.

`GET /me/messages?$search="…"` rather than `POST /search/query` with `entityTypes: ["message"]`,
which is the endpoint `teams_search_messages` uses for Teams. Three documented facts decide this
choice. All three concern the mail entity:

* **The Search API cannot reach a delegated mailbox at all** — "Users can search their own
  mailbox, but can't search delegated mailboxes"
  (https://learn.microsoft.com/en-us/graph/search-concept-messages). `$search` on the collection
  has no such restriction, so the shape stays open to a shared-mailbox tool later.
* **Its message hit carries no `id`.** The documented projection is `createdDateTime`,
  `lastModifiedDateTime`, `receivedDateTime`, `sentDateTime`, `hasAttachments`, `subject`,
  `bodyPreview`, `importance`, `replyTo`, `sender` and `from`. Microsoft documents `hitId` as a
  separate field, of type `RestId`. `fields` only narrows a message hit. It cannot add back a
  field Graph left out.
* **Its `total` is the page size, not the match count**, exactly as for `chatMessage`.

**Two Graph calls, and the second is not optional.** `Prefer: IdType="ImmutableId"` is *not*
honoured on a `$search` request. Graph answers `Preference-Applied` anyway, so the header lies
rather than fails. Microsoft's own maintainer confirmed this in
https://github.com/microsoftgraph/msgraph-sdk-dotnet/issues/698 with "the immutableId is not
supported with $search query parameters when targeting messages. You'd need to make a secondary
call to translate those IDs … using the translateExchangeIds API." A handle minted from the raw
hit id dies the moment Outlook files the message. Inbox rules and retention can file a message
with no warning, and when this happens, the model reports the message as deleted. So every id
here is exchanged before it becomes a handle. The exchange costs no extra consent: `User.Read` is
already always on.

**One request, `$top` is the window.** Whether `$search` paging works on this collection is
undocumented. No Microsoft page shows an `@odata.nextLink` on a searched message collection. So
this tool asks once for what the caller wants, instead of a walk with an unverified stop
condition. Microsoft documents a `$search` limit of at most 1000 results, and `limit` here stays
far below that.

**No date arguments, and no `$orderby`.** Microsoft documents `received` as an exact-date KQL
property on this collection and publishes no range syntax for it. Graph fails unsupported
query-parameter combinations *silently* rather than with an error
(https://learn.microsoft.com/en-us/graph/query-parameters). If Graph silently ignores
`$orderby`, it still returns results in its own order, under a label that promises a different
order. Date-bounded questions are `outlook_list_mail`, which filters and sorts on one property
and cannot be silently ignored.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.tools import tool as tool_metadata
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.exchange_id_format import ExchangeIdFormat
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.messages.messages_request_builder import MessagesRequestBuilder
from msgraph.generated.users.item.translate_exchange_ids.translate_exchange_ids_post_request_body import (  # noqa: E501
    TranslateExchangeIdsPostRequestBody,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared import kql
from office_365_mcp.shared.mail import SUMMARY_FIELDS, MailSummary
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_search_mail"

STEP_SEARCH = "mail_search"
STEP_IDS = "mail_ids"

# `Mail.Read` covers the search. `User.Read` covers the id exchange.
# `User.Read` is always on by default, but this file names it anyway.
# This tool exchanges its token for exactly the permissions declared here.
# An undeclared permission causes a 403 on the second call, and nowhere else.
GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read", "User.Read")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "invoice"}

MAX_RESULTS = 50

_DESCRIPTION = """\
Search the signed-in user's own mailbox by keyword, sender, recipient or subject. Use it for \
"find the mail where…" and for anything about a person. The tool needs at least one criterion, \
and combines all given criteria with AND. Hits carry metadata and a short preview only. Pass a \
hit's `uri` to outlook_read_mail for what the message actually says. There is no date filter and \
no sort here. Microsoft's index returns its own order. For "the newest" or "this week", use \
outlook_list_mail, which orders by receipt within one folder. This tool searches only this \
user's mailbox, never a shared one.\
"""

_NO_CRITERIA = (
    "outlook_search_mail needs at least one of query, sender, recipient or subject. Graph answers "
    + "a criteria-free search with an arbitrary slice of the mailbox. This slice is a sample of "
    + "what the user can read, not an answer. Add the words or the person the question is about."
)


class MailSearchResults(BaseModel):
    """What the mailbox index returned, and nothing about what it did not."""

    messages: list[MailSummary] = Field(
        description=(
            "The matches, ordered by send date, which is the order Microsoft's index returns. "
            + "Empty means the index matched nothing. This does not mean the mailbox holds "
            + "nothing, because a search reaches indexed content only."
        )
    )
    more_may_exist: bool = Field(
        description=(
            "When the answer fills `limit`, this is true, and a higher `limit` can return more "
            + "matches. There is no match count to report. Graph publishes none for a mail "
            + "search, and any number reported here is only this page's size, mislabeled as a "
            + "total."
        )
    )


@dataclass(frozen=True, slots=True)
class SearchCriteria:
    """What was asked for, separately from how it is spelled for Graph."""

    query: str | None = None
    sender: str | None = None
    recipient: str | None = None
    subject: str | None = None


CRITERIA: tuple[str, ...] = tuple(field.name for field in fields(SearchCriteria))


async def search_mail(
    client: GraphServiceClient, criteria: SearchCriteria, *, limit: int
) -> MailSearchResults:
    assert 1 <= limit <= MAX_RESULTS, f"limit is bounded by the schema, got {limit}"
    search = _query_string(criteria)
    if not search:
        raise ToolError(_NO_CRITERIA)

    with graph_errors(TOOL_NAME):
        with graph_step(STEP_SEARCH):
            page = await client.me.messages.get(
                request_configuration=RequestConfiguration(
                    query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                        search=kql.as_search_value(search),
                        select=list(SUMMARY_FIELDS),
                        top=limit,
                    )
                )
            )
        found = [message for message in (page.value if page is not None else None) or []]
        stable = await _stable_ids(client, found)

    return MailSearchResults(
        messages=[
            MailSummary.from_message(message, message_id=stable[message.id])
            for message in found
            if message.id is not None and message.id in stable
        ],
        more_may_exist=len(found) >= limit,
    )


async def _stable_ids(client: GraphServiceClient, found: list[Message]) -> dict[str, str]:
    """Each hit's mutable id, mapped to one that survives after the mailbox files the message.

    This exchange drops a hit that Graph fails to translate, rather than answer with the mutable
    id. A handle that works now, and then fails with a 404 within an hour, is the failure this
    exchange exists to prevent. The model reads that 404 as "deleted".
    """
    raw = [message.id for message in found if message.id is not None]
    if not raw:
        return {}
    with graph_step(STEP_IDS):
        translated = await client.me.translate_exchange_ids.post(
            TranslateExchangeIdsPostRequestBody(
                input_ids=raw,
                source_id_type=ExchangeIdFormat.RestId,
                target_id_type=ExchangeIdFormat.RestImmutableEntryId,
            )
        )
    results = (translated.value if translated is not None else None) or []
    return {
        result.source_id: result.target_id
        for result in results
        if result.source_id is not None
        and result.target_id is not None
        and result.error_details is None
    }


def _query_string(criteria: SearchCriteria) -> str:
    """The KQL string these criteria become. This string is empty when the caller gives no
    criteria.

    The property names are Microsoft's own for a message collection. A query of only punctuation
    contributes no term. So this string, not the arguments behind it, is the honest test of
    whether the caller gave a criterion.
    """
    terms: list[str] = []
    if criteria.query:
        rendered = kql.free_text(criteria.query)
        if rendered:
            terms.append(rendered)
    if criteria.sender:
        terms.append(f"from:{kql.quoted(criteria.sender)}")
    if criteria.recipient:
        terms.append(f"participants:{kql.quoted(criteria.recipient)}")
    if criteria.subject:
        terms.append(f"subject:{kql.quoted(criteria.subject)}")
    return " ".join(terms)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @tool_metadata(
        name=TOOL_NAME,
        title="Search Mail",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_search_mail(
        query: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Words to find in the subject, the body or an attachment's text. Every word "
                    + "must appear, in any order. Quote a run to require adjacency: "
                    + '`"purchase order"` matches only side by side, `purchase order` matches '
                    + "both words anywhere. This tool treats search operators as plain text. It "
                    + "does not act on them as commands."
                ),
            ),
        ] = None,
        sender: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail from this person, by address, alias or display name. Exchange "
                    + "expands a name to the address it knows, so a first name usually works. Do "
                    + "not put the person's name in `query` instead: `query` also matches mail "
                    + "that merely mentions them."
                ),
            ),
        ] = None,
        recipient: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail this person was on, as sender or as any recipient including Bcc. "
                    + "Use the signed-in user's own address, from get_me, for \"mail addressed to "
                    + 'me". Use `sender` for "mail from them".'
                ),
            ),
        ] = None,
        subject: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail whose subject carries these words. Narrower than `query`, which "
                    + "reads the body too, and the better choice when the user quoted a subject."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=(
                    f"How many messages to return, at most {MAX_RESULTS}. One Graph request, so "
                    + "this is the whole window rather than a first page: raise it rather than "
                    + "calling again with the same criteria."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> MailSearchResults:
        return await search_mail(
            client,
            SearchCriteria(query=query, sender=sender, recipient=recipient, subject=subject),
            limit=limit,
        )

    _require_a_criterion(mcp.add_tool(outlook_search_mail))


def _require_a_criterion(tool: Tool) -> None:
    """Say "at least one of these" in the schema, which a Python signature cannot express.

    The runtime refusal stays. FastMCP validates arguments against the signature, not against
    this schema. So a client that ignores `anyOf` still receives the refusal at runtime.
    """
    tool.parameters["anyOf"] = [{"required": [name]} for name in CRITERIA]
