"""`outlook_search_mail` — find a message anywhere in the signed-in user's mailbox.

`GET /me/messages?$search="…"` rather than `POST /search/query`, which cannot reach a delegated
mailbox at all (https://learn.microsoft.com/en-us/graph/search-concept-messages).
`Prefer: IdType="ImmutableId"` is not honoured under `$search` and Graph answers
`Preference-Applied` anyway, so every hit id is exchanged through `translateExchangeIds`
(https://github.com/microsoftgraph/msgraph-sdk-dotnet/issues/698) before it becomes a handle.
Paging is undocumented here, so this asks once and `$top` is the window; `$orderby` is ignored
silently, so there is none. The date bounds go in the KQL, because a `$filter` beside `$search` is
refused with `SearchWithFilter` — a live probe on 2026-09-10 matched `received>=`, `received<` and
`received<=` against the equivalent `receivedDateTime` `$filter` row for row, while
`received>=today-5` returned nothing silently and `received:"last week"` was a 400. `$search` does
not reach drafts in Deleted Items, so a window here under-returns where `outlook_list_mail` does
not.

**`mailbox` re-points every request from `/me` to `/users/{id}`, `translateExchangeIds` included.**

**`attachment_name` is the only route to an attachment here, and it is a route to its NAME.**
Neither `$search` nor the Microsoft Search API can index attachment content for a delegated
mailbox from this connector. `attachment_name` matches a file name only. It never searches inside
a file.
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
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared import kql
from office_365_mcp.shared.mail import SUMMARY_FIELDS, MailSummary
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    READ_ONLY,
    graph_client_for_caller,
    graph_mailbox,
)
from office_365_mcp.shared.window import closes_at, opens_at, runs_backwards

TOOL_NAME = "outlook_search_mail"

STEP_SEARCH = "mail_search"
STEP_IDS = "mail_ids"

# `User.Read` covers the id exchange, which is the only call that 403s without it.
GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read", "User.Read", "Mail.Read.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "invoice"}

MAX_RESULTS = 50

_DESCRIPTION = """\
Searches the signed-in user's own mailbox by keyword, sender, recipient, subject, or attachment \
file name for "find the mail where…" questions and anything about a person. outlook_list_mail \
is the sibling for a folder's newest mail in receipt order, including drafts. For a plain date \
window, or when order matters, use it instead.

Notes:
- Needs at least one of `query`, `sender`, `recipient`, `to`, `subject`, or `attachment_name`. \
`received_after` and `received_before` narrow that criterion but never substitute for one, and \
all given criteria must match (AND).
- `received_before` must fall on or after `received_after`. A reversed pair returns nothing.
- Searches the signed-in user's own mailbox unless `mailbox` names a shared or delegated one.
"""


class MailSearchResults(BaseModel):
    """What the mailbox index returned, and nothing about what it did not."""

    messages: list[MailSummary] = Field(
        description=(
            "The matches, in the index's own order — not receipt or send order, and not "
            + "necessarily newest first. Empty means the index found nothing, not that the "
            + "mailbox holds nothing: a search reaches indexed content only. Pass a hit's `uri` "
            + "to outlook_read_mail for the full message. The `uri` continues to work after the "
            + "message is later moved, renamed, or refiled."
        )
    )
    more_may_exist: bool = Field(
        description=(
            "True means the answer fills `limit`, so more matches can exist. There is no match "
            + "count to report. Raise `limit` to see more. Calling again with the same "
            + "arguments returns the same page, not the next one."
        )
    )


@dataclass(frozen=True, slots=True)
class SearchCriteria:
    query: str | None = None
    sender: str | None = None
    recipient: str | None = None
    to: str | None = None
    subject: str | None = None
    attachment_name: str | None = None


CRITERIA: tuple[str, ...] = tuple(field.name for field in fields(SearchCriteria))

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
    mailbox: str | None = None,
) -> MailSearchResults:
    assert 1 <= limit <= MAX_RESULTS, f"limit is bounded by the schema, got {limit}"
    asked = _query_string(criteria)
    if not asked:
        raise ToolError(_NO_CRITERIA)
    if runs_backwards(received_after, received_before):
        raise ToolError(_WINDOW_RUNS_BACKWARDS)
    search = " AND ".join([asked, *_window_terms(received_after, received_before)])
    reached = graph_mailbox(client, mailbox)

    with graph_errors(TOOL_NAME):
        with graph_step(STEP_SEARCH):
            page = await reached.messages.get(
                request_configuration=RequestConfiguration(
                    query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                        search=kql.as_search_value(search),
                        select=list(SUMMARY_FIELDS),
                        top=limit,
                    )
                )
            )
        found = [message for message in (page.value if page is not None else None) or []]
        stable = await _stable_ids(reached, found)

    return MailSearchResults(
        messages=[
            MailSummary.from_message(message, message_id=stable[message.id])
            for message in found
            if message.id is not None and message.id in stable
        ],
        more_may_exist=len(found) >= limit,
    )


async def _stable_ids(reached: UserItemRequestBuilder, found: list[Message]) -> dict[str, str]:
    """Each hit's mutable id, mapped to one that survives after the mailbox files the message.

    A hit Graph fails to translate is dropped rather than handed back with its mutable id.
    """
    raw = [message.id for message in found if message.id is not None]
    if not raw:
        return {}
    with graph_step(STEP_IDS):
        translated = await reached.translate_exchange_ids.post(
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

    Properties per https://learn.microsoft.com/en-us/graph/search-query-parameter. A query of only
    punctuation contributes no term, so this string is the honest test of a criterion."""
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

    Joined with an explicit `AND`, never a space: two space-separated `received` comparisons are
    both dropped, answering the criterion's own unbounded matches. Unquoted, because `kql.quoted`
    would phrase-quote an instant for its colons into a form no probe verified.
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
    """Either spelling covers the whole of the value the caller named."""
    if isinstance(received_before, datetime):
        return f"received<={_wire(closes_at(received_before))}"
    return f"received<{_wire(opens_at(received_before + timedelta(days=1)))}"


def _wire(instant: datetime) -> str:
    """An instant as the UTC literal the live probe verified, keeping whatever precision it has.

    Renders identically to `outlook_list_mail._wire`, so the two windows read against each other.
    Truncating to whole seconds moves a bound silently and drops a row at the boundary."""
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
                    "Words to find in the subject or the body — NOT an attachment's text. This "
                    + "tool cannot reach that. Use `attachment_name` for a file's name instead. "
                    + "Every word must appear, in any order. Quote a run to require adjacency. "
                    + '`"purchase order"` matches only side by side. `purchase order` matches '
                    + "both words anywhere. This tool reads search operators in this text "
                    + "literally, and never executes them as commands."
                ),
            ),
        ] = None,
        sender: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail from this person, by address, alias, or display name. Exchange "
                    + "expands a name to the address it knows, so a first name usually works. "
                    + "Put a name here rather than in `query`, which also matches mail that "
                    + "merely mentions them."
                ),
            ),
        ] = None,
        recipient: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail this person appears on anywhere — as sender, or as a To, Cc, or "
                    + "Bcc recipient. On the user's own mailbox that is nearly every message, so "
                    + 'it is the wrong argument for "addressed to me". Use `to` for that and '
                    + "`sender` for mail from them."
                ),
            ),
        ] = None,
        to: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail addressed directly to this person on the To line, not Cc, Bcc, or "
                    + 'mail they merely sent. This is the argument for "addressed to me". Pass '
                    + "the signed-in user's own address from get_me. Takes an address, alias, or "
                    + "display name, as `sender` does."
                ),
            ),
        ] = None,
        subject: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail whose subject carries these words. Narrower than `query`, which "
                    + "also reads the body. If the user quoted a subject, prefer this field."
                ),
            ),
        ] = None,
        attachment_name: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only mail with an attachment whose file name matches, for example "
                    + "`budget_2026.xlsx`. No other argument reaches a file name. The match "
                    + "works by word, not by substring. `budget.xlsx` also finds "
                    + "`2017 budget.xlsx`. But a fragment such as `budg` matches nothing, rather "
                    + "than a prefix. This is not a has-any-attachment switch. Read the "
                    + "`has_attachments` output field for that instead."
                ),
            ),
        ] = None,
        received_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only mail received on or after this point. A date (`2026-03-04`) covers "
                    + "that whole UTC day from its first instant. A moment "
                    + "(`2026-03-04T09:00:00Z`) opens at the exact second named, and one with no "
                    + "time zone is read as UTC."
                )
            ),
        ] = None,
        received_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only mail received on or before this point, inclusive, in the same two "
                    + "shapes as `received_after`. A date closes at the end of that UTC day, so "
                    + "the same date in both bounds searches exactly that one day."
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
                    + "this is the whole window rather than a first page. Raise it instead of "
                    + "calling again with the same criteria."
                ),
            ),
        ] = 25,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
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
            mailbox=mailbox,
        )

    _require_a_criterion(mcp.add_tool(outlook_search_mail))


def _require_a_criterion(tool: Tool) -> None:
    """Say "at least one of these" in the schema, which a Python signature cannot express.

    FastMCP validates arguments against the signature rather than this schema, so the runtime
    refusal stays.
    """
    tool.parameters["anyOf"] = [{"required": [name]} for name in CRITERIA]
