from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
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

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read", "User.Read", "Mail.Read.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "invoice"}

MAX_RESULTS = 50

_DESCRIPTION = (
    "Searches the signed-in user's own mailbox by keyword, sender, recipient, subject, or "
    "attachment file name."
)


class MailSearchResults(BaseModel):
    messages: list[MailSummary] = Field(
        description="The matches, in the index's own order, not necessarily newest first."
    )
    more_may_exist: bool = Field(
        description="True if the answer fills limit, so more matches can exist."
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
    terms: list[str] = []
    if received_after is not None:
        terms.append(_opening_term(received_after))
    if received_before is not None:
        terms.append(_closing_term(received_before))
    return terms


def _opening_term(received_after: date | datetime) -> str:
    return f"received>={_wire(opens_at(received_after))}"


def _closing_term(received_before: date | datetime) -> str:
    if isinstance(received_before, datetime):
        return f"received<={_wire(closes_at(received_before))}"
    return f"received<{_wire(opens_at(received_before + timedelta(days=1)))}"


def _wire(instant: datetime) -> str:
    if instant.microsecond:
        return f"{instant:%Y-%m-%dT%H:%M:%S.%f}Z"
    return f"{instant:%Y-%m-%dT%H:%M:%SZ}"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
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
                description="Words to find in the subject or body, not an attachment's text.",
            ),
        ] = None,
        sender: Annotated[
            str | None,
            Field(min_length=1, description="Only mail from this person."),
        ] = None,
        recipient: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Only mail this person appears on anywhere, as sender or recipient.",
            ),
        ] = None,
        to: Annotated[
            str | None,
            Field(min_length=1, description="Only mail addressed directly to this person."),
        ] = None,
        subject: Annotated[
            str | None,
            Field(min_length=1, description="Only mail whose subject carries these words."),
        ] = None,
        attachment_name: Annotated[
            str | None,
            Field(
                min_length=1,
                description="Only mail with an attachment whose file name matches.",
            ),
        ] = None,
        received_after: Annotated[
            date | datetime | None,
            Field(description="Only mail received on or after this date or moment."),
        ] = None,
        received_before: Annotated[
            date | datetime | None,
            Field(description="Only mail received on or before this date or moment."),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=f"How many messages to return, at most {MAX_RESULTS}.",
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
