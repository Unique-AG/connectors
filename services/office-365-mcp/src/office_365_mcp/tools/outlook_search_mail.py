"""`outlook_search_mail` — find a message anywhere in the signed-in user's mailbox.

`GET /me/messages?$search="…"` rather than `POST /search/query` with `entityTypes: ["message"]`,
the endpoint `teams_search_messages` uses. Three facts about the mail entity decide it. The Search
API cannot reach a delegated mailbox at all — "Users can search their own mailbox, but can't
search delegated mailboxes" (https://learn.microsoft.com/en-us/graph/search-concept-messages) — so
`$search` keeps the shape open to a shared-mailbox tool later. Its message hit carries no `id`,
documented only by example: both sample projections omit it and offer `hitId` instead, a `RestId`
for a message (https://learn.microsoft.com/en-us/graph/api/resources/searchhit), and `fields`
cannot add back a field Graph left out. And its `total` is the page size, not the match count.

**Two Graph calls, and the second is not optional.** `Prefer: IdType="ImmutableId"` is not
honoured under `$search`, and Graph answers `Preference-Applied` anyway, so the header lies rather
than fails; Microsoft's own maintainer says to "make a secondary call to translate those IDs …
using the translateExchangeIds API"
(https://github.com/microsoftgraph/msgraph-sdk-dotnet/issues/698). A handle minted from the raw
hit id dies the moment an inbox rule or retention files the message, and a model reads that 404 as
"deleted". So every id is exchanged before it becomes a handle. `User.Read` covers the exchange
and is always on.

**One request, and `$top` is the window.** Whether `$search` pages on this collection is
undocumented, and no Microsoft page shows an `@odata.nextLink` on a searched message collection.
So this tool asks once rather than walking with an unverified stop condition.

**The date bound goes in the KQL, and nowhere else.** A live probe against a real tenant on
2026-09-10 sent `received>=`, `received<` and `received<=` with full ISO instants beside the
equivalent `receivedDateTime` `$filter` over the same mailbox: identical row sets in all six
paired comparisons, fractional seconds and a non-UTC offset both honoured, and
`received>=2099-01-01` returned nothing — so the operator is applied rather than degraded to free
text. A `$filter` beside `$search` is refused outright, `SearchWithFilter`, reproduced on three
different arguments. That 400 is louder than Microsoft's published rule for an unsupported
combination, which is to fail *silently*
(https://learn.microsoft.com/en-us/graph/query-parameters) and would drop the bound and answer the
whole `$top` window under an argument named for a date. Only absolute instants are safe: the same
probe found `received>=today-5` returns zero rows silently, and `received:"last week"` is a 400.

**The window can under-return and never over-return.** The same probe found `$search` does not
reach drafts in Deleted Items, which `$filter` does — 3 rows of 32 over one month, ~106 of 378
over the whole mailbox. That is the direction every other criterion here already fails in, and
`outlook_list_mail` is what reaches those rows.

**Still no `$orderby`.** Ignored under `$search`, and silently, it would return the index's own
order under a label promising receipt order. So recency stays `outlook_list_mail`, which sorts and
filters the property Exchange itself evaluates.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta
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
from office_365_mcp.shared.window import closes_at, opens_at, runs_backwards

TOOL_NAME = "outlook_search_mail"

STEP_SEARCH = "mail_search"
STEP_IDS = "mail_ids"

# The token is exchanged for exactly these, so an undeclared `User.Read` 403s the id exchange
# alone, on the second call and nowhere else.
GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read", "User.Read")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "invoice"}

MAX_RESULTS = 50

_DESCRIPTION = """\
Search the signed-in user's own mailbox by keyword, sender, recipient, subject or attachment \
file name, within a receipt-date window when the question has one. Use it for "find the mail \
where…" and for anything about a person. The tool needs at least one criterion, and combines all \
given criteria with AND, so each one narrows the answer. Pick the recipient argument \
deliberately: `to` is the To line only, which is what "addressed to me" means, while `recipient` \
also matches Cc, Bcc and mail the person sent — on the user's own mailbox that is nearly \
everything. `attachment_name` is the only way to reach a file's name; `query` does not read it. \
`received_after` and `received_before` bound receipt date at either end, and both of those days \
are covered whole, so "the invoice mail from March" is one call. They narrow a search rather than \
standing in for one: at least one criterion is still required, because a window on its own is \
outlook_list_mail's question. There is no sort here, inside a window or outside one. Microsoft's \
index returns its own order, so a window does not make an answer "the newest". Hits carry \
metadata and a short preview only. Pass a hit's `uri` to outlook_read_mail for what the message \
actually says. Use outlook_list_mail instead for a date range with nothing to search for, for \
"the newest" and anything else about receipt order, and when unsent drafts matter: the index \
behind this tool does not reach drafts in Deleted Items, so a window here can return fewer \
messages than the same window on outlook_list_mail, never more. This tool searches only this \
user's mailbox, never a shared one.\
"""


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
    to: str | None = None
    subject: str | None = None
    attachment_name: str | None = None


CRITERIA: tuple[str, ...] = tuple(field.name for field in fields(SearchCriteria))

# Spelled from `CRITERIA`, so the refusal always lists the arguments the schema publishes as the
# way out of it.
_NO_CRITERIA = (
    f"outlook_search_mail needs at least one of {', '.join(CRITERIA[:-1])} or {CRITERIA[-1]}. "
    + "Graph answers a criteria-free search with an arbitrary slice of the mailbox. This slice is "
    + "a sample of what the user can read, not an answer. Add the words or the person the "
    + "question is about. `received_after` and `received_before` narrow a search and are not "
    + "criteria: a date range with nothing to search for is outlook_list_mail, which orders by "
    + "receipt and reaches drafts this index does not."
)

_WINDOW_RUNS_BACKWARDS = (
    "outlook_search_mail searched nothing, because `received_before` falls before "
    + "`received_after` and no mailbox holds a window that runs backwards. A date covers the whole "
    + "of the day it names at either end, so one date in both bounds searches that single day. "
    + "Put the earlier point in `received_after` and the later one in `received_before`, then call "
    + "again. Retrying with the same two values will fail identically."
)


async def search_mail(
    client: GraphServiceClient,
    criteria: SearchCriteria,
    *,
    received_after: date | datetime | None = None,
    received_before: date | datetime | None = None,
    limit: int,
) -> MailSearchResults:
    assert 1 <= limit <= MAX_RESULTS, f"limit is bounded by the schema, got {limit}"
    asked = _query_string(criteria)
    if not asked:
        raise ToolError(_NO_CRITERIA)
    if runs_backwards(received_after, received_before):
        raise ToolError(_WINDOW_RUNS_BACKWARDS)
    search = " AND ".join([asked, *_window_terms(received_after, received_before)])

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

    A hit Graph fails to translate is dropped rather than answered with the mutable id: a handle
    that works now and 404s within the hour is the failure this call exists to prevent.
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
    """The KQL these criteria become, empty exactly when the caller named none.

    Every property is Microsoft's own for a message collection, published with an example against
    `/me/messages` (https://learn.microsoft.com/en-us/graph/search-query-parameter). A query of
    only punctuation contributes no term, so this string is the honest test of a criterion."""
    terms: list[str] = []
    if criteria.query:
        rendered = kql.free_text(criteria.query)
        if rendered:
            terms.append(rendered)
    if criteria.sender:
        terms.append(f"from:{kql.quoted(criteria.sender)}")
    if criteria.recipient:
        terms.append(f"participants:{kql.quoted(criteria.recipient)}")
    if criteria.to:
        terms.append(f"to:{kql.quoted(criteria.to)}")
    if criteria.subject:
        terms.append(f"subject:{kql.quoted(criteria.subject)}")
    if criteria.attachment_name:
        terms.append(f"attachment:{kql.quoted(criteria.attachment_name)}")
    return " ".join(terms)


def _window_terms(
    received_after: date | datetime | None, received_before: date | datetime | None
) -> list[str]:
    """The bounds as KQL comparisons on `received`, at most one per end.

    Joined to the criteria and to each other with the explicit `AND`, never a space: a live probe
    on 2026-09-10 found two space-separated `received` comparisons are BOTH DROPPED, returning the
    criterion's own unbounded matches under a windowed argument. `AND` matched the equivalent
    `receivedDateTime` `$filter` exactly in every shape tried.

    Not quoted. The value is a pydantic-parsed date or moment, so it carries no quote and no
    operator, and `kql.quoted` would phrase-quote it for its colons into a form no probe verified.
    """
    terms: list[str] = []
    if received_after is not None:
        terms.append(_opening_term(received_after))
    if received_before is not None:
        terms.append(_closing_term(received_before))
    return terms


def _opening_term(received_after: date | datetime) -> str:
    """`received>=` the first instant the bound admits, which for a date is that day's."""
    return f"received>={_wire(opens_at(received_after))}"


def _closing_term(received_before: date | datetime) -> str:
    """`received<` the day after a date, `received<=` a named moment.

    Both are the same promise, that the value named is inside the window: half-open on the
    following day covers a whole day without choosing a precision, and a moment is exact already.
    """
    if isinstance(received_before, datetime):
        return f"received<={_wire(closes_at(received_before))}"
    return f"received<{_wire(opens_at(received_before + timedelta(days=1)))}"


def _wire(instant: datetime) -> str:
    """An instant as the UTC literal the live probe verified, keeping whatever precision it has.

    `outlook_list_mail._wire` renders a bound identically, so the two windows read against each
    other. Truncating to whole seconds widens the lower bound and narrows the upper, and a row
    lost at that boundary leaves a well-formed answer that says nothing was dropped."""
    if instant.microsecond:
        return f"{instant:%Y-%m-%dT%H:%M:%S.%f}Z"
    return f"{instant:%Y-%m-%dT%H:%M:%SZ}"


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
                    "Only mail this person was on ANYWHERE — as the sender, or as a To, Cc or "
                    + 'Bcc recipient. That width makes it the wrong argument for "mail addressed '
                    + "to me\": on the user's own mailbox nearly every message has them on it "
                    + "somewhere, so this matches nearly everything. Use `to` for that, `sender` "
                    + 'for "mail from them", and this one for "anything involving Dana".'
                ),
            ),
        ] = None,
        to: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail addressed directly to this person, on the To line — not Cc, not "
                    + 'Bcc, and not mail they merely sent. This is the argument for "mail '
                    + "addressed to me\", with the signed-in user's own address from get_me: it "
                    + "separates the mail written to them from the mail they were copied on. "
                    + "Takes an address, alias or display name, as `sender` does."
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
        attachment_name: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail carrying an attachment whose FILE NAME matches, for example "
                    + "`budget_2026.xlsx`. Attachment file names are reachable by no other "
                    + "argument here: `query` reads the sender, the subject and the body text, "
                    + "and a file's name is in none of them. Pass the name whole and as the user "
                    + "wrote it. Matching is on the words of the name rather than the name "
                    + "itself, so `budget.xlsx` also finds `2017 budget.xlsx`, while a fragment "
                    + "such as `budg` finds neither — this tool sends `*` as a literal, so a "
                    + "partial name silently returns nothing instead of matching a prefix. This "
                    + "is not a has-any-attachment switch: every row already reports "
                    + "`has_attachments`, so read that field rather than inventing a name here."
                ),
            ),
        ] = None,
        received_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only mail received on or after this point, inclusive. Two shapes: a date, "
                    + "`2026-03-04`, which is that whole UTC day from its first instant; or a "
                    + "moment, `2026-03-04T09:00:00Z`, which is the second it names. A moment "
                    + "carrying no zone is read as UTC, so a user's early morning or late evening "
                    + "can fall on the neighbouring UTC day. This narrows the criteria and does "
                    + "not stand in for one: a criterion is still required, and a window with "
                    + "nothing to search for is outlook_list_mail's question. It does not order "
                    + "the answer either — hits come back in the index's own order inside a "
                    + "window exactly as outside one, so this is not a way to ask for the newest."
                )
            ),
        ] = None,
        received_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only mail received on or before this point, inclusive, in the same two "
                    + "shapes `received_after` takes. A date closes at the END of that UTC day, "
                    + "so the whole of it is inside the bound and the same date in both bounds "
                    + "searches that one day; a moment closes at the second it names. Pair it "
                    + 'with `received_after` for a window that has closed — "the invoice mail '
                    + 'from March", "what Dana sent last week". Like `received_after` it narrows '
                    + "a search rather than being one, and it sorts nothing: for "
                    + "recency or receipt order, and for the drafts this index does not reach, "
                    + "use outlook_list_mail."
                )
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
            SearchCriteria(
                query=query,
                sender=sender,
                recipient=recipient,
                to=to,
                subject=subject,
                attachment_name=attachment_name,
            ),
            received_after=received_after,
            received_before=received_before,
            limit=limit,
        )

    _require_a_criterion(mcp.add_tool(outlook_search_mail))


def _require_a_criterion(tool: Tool) -> None:
    """Say "at least one of these" in the schema, which a Python signature cannot express.

    The runtime refusal stays. FastMCP validates arguments against the signature, not against
    this schema. So a client that ignores `anyOf` still receives the refusal at runtime.
    """
    tool.parameters["anyOf"] = [{"required": [name]} for name in CRITERIA]
