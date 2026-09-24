import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.message import Message
from msgraph.generated.models.person import Person
from msgraph.generated.models.person_type import PersonType
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.scored_email_address import ScoredEmailAddress
from msgraph.generated.models.user import User
from msgraph.generated.users.item.messages.messages_request_builder import MessagesRequestBuilder
from msgraph.generated.users.item.people.people_request_builder import PeopleRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared import identity, kql
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_find_recipient"

STEP_PEOPLE = "people_search"
STEP_PARTICIPANTS = "mail_participants"

GRAPH_PERMISSIONS: tuple[str, ...] = ("People.Read", "Mail.Read", identity.GRAPH_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "Tyler"}

MAX_RESULTS = 50

_QUERY_SOURCES = ("X-PeopleQuery-QuerySources", "Mailbox,Directory")

_PERSON_FIELDS = (
    "displayName",
    "scoredEmailAddresses",
    "userPrincipalName",
    "personType",
    "jobTitle",
    "department",
)

_PARTICIPANT_FIELDS = ("from", "toRecipients", "ccRecipients", "receivedDateTime")

_PARTICIPANT_MESSAGES = 50

type MatchKind = Literal["exact", "token", "fuzzy"]
type RecipientKind = Literal["person", "group", "room"]
type RecipientSource = Literal["people", "mailbox"]
type Outcome = Literal["match", "no_match"]

type _PeopleQuery = PeopleRequestBuilder.PeopleRequestBuilderGetQueryParameters
type _MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_RANK: Mapping[MatchKind, int] = {"exact": 0, "token": 1, "fuzzy": 2}

_WORD = re.compile(r"[^\W_]+")

_NEVER = datetime.min.replace(tzinfo=UTC)

_DESCRIPTION = (
    "Resolves a name, alias, or partial address to who it can mean; never pick a candidate "
    "automatically — let the user choose, especially an `ambiguous` or `fuzzy` one."
)

_NO_QUERY = (
    "outlook_find_recipient needs a name, an alias or an address to look for, and this query "
    + "carries no word to match on. Graph answers an empty person search with an arbitrary slice "
    + "of the user's relevance list. That slice is a sample of who they know, not an answer."
)


class RecipientCandidate(BaseModel):
    address: str = Field(description="The SMTP address to put on a draft; never the sign-in name.")
    display_name: str | None = Field(
        description=(
            "The name shown for this address; on a `mailbox` row it is chosen by the sender, "
            + "not a directory fact."
        )
    )
    match_kind: MatchKind = Field(
        description=(
            "How this row compares to the query: `exact`, `token`, or `fuzzy`; never draft to "
            + "a `fuzzy` row without asking first."
        )
    )
    kind: RecipientKind | None = Field(
        description=(
            "What the address belongs to: `person`, `group`, or `room`; null on a `mailbox` "
            + "row."
        )
    )
    external: bool | None = Field(
        description="True when the address's domain differs from the signed-in user's own."
    )
    job_title: str | None = Field(
        description="The job title from the directory, when recorded; null on a `mailbox` row."
    )
    department: str | None = Field(
        description="The department from the directory, when recorded; null on a `mailbox` row."
    )
    source: RecipientSource = Field(
        description=(
            "Which index answered: `people` (Microsoft's relevance list) or `mailbox` (a "
            + "fallback over past mail — make sure a human reviews it)."
        )
    )
    ever_corresponded: bool = Field(
        description="True when this tool found this address on a message in the user's own mailbox."
    )


class RecipientCandidates(BaseModel):
    outcome: Outcome = Field(
        description=(
            "`match` when at least one candidate came back; `no_match` is never proof the "
            + "person does not exist."
        )
    )
    query: str = Field(description="The query exactly as it was sent.")
    candidates: list[RecipientCandidate] = Field(
        description=(
            "Candidates, strongest `match_kind` first; the first entry is not a choice made "
            + "for the caller."
        )
    )
    ambiguous: bool = Field(
        description=(
            "True when more than one candidate shares the best `match_kind`; put the choice to "
            + "the user."
        )
    )


@dataclass(frozen=True, slots=True)
class _Caller:
    address: str | None
    domain: str | None

    @classmethod
    def of(cls, user: User) -> _Caller:
        address = user.mail or user.user_principal_name
        return cls(address=address, domain=None if address is None else _domain_of(address))


async def find_recipient(
    client: GraphServiceClient, *, query: str, limit: int
) -> RecipientCandidates:
    assert 1 <= limit <= MAX_RESULTS, f"limit is bounded by the schema, got {limit}"
    if not _tokens(query):
        raise ToolError(_NO_QUERY)

    with graph_errors(TOOL_NAME):
        caller = _Caller.of(await identity.signed_in_user(client))
        found = await _people(client, query, caller=caller, limit=limit)
        if not found:
            found = await _correspondents(client, query, caller=caller, limit=limit)

    ranked = sorted(found, key=_rank_of)
    return RecipientCandidates(
        outcome="match" if ranked else "no_match",
        query=query,
        candidates=ranked,
        ambiguous=_ambiguous(ranked),
    )


async def _people(
    client: GraphServiceClient, query: str, *, caller: _Caller, limit: int
) -> list[RecipientCandidate]:
    configuration = RequestConfiguration[_PeopleQuery](
        query_parameters=PeopleRequestBuilder.PeopleRequestBuilderGetQueryParameters(
            search=kql.as_search_value(query),
            select=list(_PERSON_FIELDS),
            top=limit,
        ),
        headers=_headers(),
    )
    with graph_step(STEP_PEOPLE):
        page = await client.me.people.get(request_configuration=configuration)

    people = (page.value if page is not None else None) or []
    return [
        candidate
        for candidate in (_from_person(person, query=query, caller=caller) for person in people)
        if candidate is not None
    ]


async def _correspondents(
    client: GraphServiceClient, query: str, *, caller: _Caller, limit: int
) -> list[RecipientCandidate]:
    configuration = RequestConfiguration[_MessagesQuery](
        query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            search=kql.as_search_value(f"participants:{kql.quoted(query)}"),
            select=list(_PARTICIPANT_FIELDS),
            top=_PARTICIPANT_MESSAGES,
        )
    )
    with graph_step(STEP_PARTICIPANTS):
        page = await client.me.messages.get(request_configuration=configuration)

    messages = (page.value if page is not None else None) or []
    return _from_messages(messages, query=query, caller=caller, limit=limit)


def _from_messages(
    messages: Sequence[Message], *, query: str, caller: _Caller, limit: int
) -> list[RecipientCandidate]:
    strongest: dict[str, tuple[RecipientCandidate, datetime]] = {}
    for message in messages:
        seen_at = _when(message.received_date_time)
        for recipient in _participants_of(message):
            candidate = _from_recipient(recipient, query=query, caller=caller)
            if candidate is None:
                continue
            key = candidate.address.casefold()
            previous = strongest.get(key)
            if previous is None:
                strongest[key] = (candidate, seen_at)
            else:
                kept, when = previous
                strongest[key] = (min(kept, candidate, key=_rank_of), max(when, seen_at))

    by_recency = sorted(strongest.values(), key=lambda row: row[1], reverse=True)
    return [candidate for candidate, _seen_at in by_recency][:limit]


def _from_person(person: Person, *, query: str, caller: _Caller) -> RecipientCandidate | None:
    address = _sendable(person.scored_email_addresses)
    if address is None:
        return None
    return RecipientCandidate(
        address=address,
        display_name=person.display_name,
        match_kind=_match_kind(
            query,
            display_name=person.display_name,
            address=address,
            principal_name=person.user_principal_name,
        ),
        kind=_kind_of(person.person_type),
        external=_external(address, caller.domain),
        job_title=person.job_title,
        department=person.department,
        source="people",
        ever_corresponded=False,
    )


def _from_recipient(
    recipient: Recipient, *, query: str, caller: _Caller
) -> RecipientCandidate | None:
    email = recipient.email_address
    if email is None or not email.address:
        return None
    if caller.address is not None and email.address.casefold() == caller.address.casefold():
        return None
    if not _mentions(query, display_name=email.name, address=email.address):
        return None
    return RecipientCandidate(
        address=email.address,
        display_name=email.name,
        match_kind=_match_kind(query, display_name=email.name, address=email.address),
        kind=None,
        external=_external(email.address, caller.domain),
        job_title=None,
        department=None,
        source="mailbox",
        ever_corresponded=True,
    )


def _participants_of(message: Message) -> list[Recipient]:
    return [
        recipient
        for recipient in (
            message.from_,
            *(message.to_recipients or []),
            *(message.cc_recipients or []),
        )
        if recipient is not None
    ]


def _sendable(addresses: list[ScoredEmailAddress] | None) -> str | None:
    for scored in addresses or []:
        if scored.address:
            return scored.address
    return None


def _kind_of(person_type: PersonType | None) -> RecipientKind | None:
    if person_type is None:
        return None
    if (person_type.subclass or "").casefold() in {"room", "equipment"}:
        return "room"
    match (person_type.class_ or "").casefold():
        case "group":
            return "group"
        case "person":
            return "person"
        case _:
            return None


def _external(address: str, own_domain: str | None) -> bool | None:
    domain = _domain_of(address)
    if own_domain is None or domain is None:
        return None
    return domain != own_domain


def _match_kind(
    query: str,
    *,
    display_name: str | None,
    address: str,
    principal_name: str | None = None,
) -> MatchKind:
    local = address.partition("@")[0]
    exact = {_folded(address), _folded(local)}
    if display_name:
        exact.add(_folded(display_name))
    if principal_name:
        exact.add(_folded(principal_name))
    if _folded(query) in exact:
        return "exact"
    if _tokens(query) <= _tokens(local) | _tokens(display_name or ""):
        return "token"
    return "fuzzy"


def _mentions(query: str, *, display_name: str | None, address: str) -> bool:
    wanted = _folded(query)
    return wanted in _folded(address) or (
        display_name is not None and wanted in _folded(display_name)
    )


def _ambiguous(candidates: Sequence[RecipientCandidate]) -> bool:
    if not candidates:
        return False
    best = min(_rank_of(candidate) for candidate in candidates)
    return sum(1 for candidate in candidates if _rank_of(candidate) == best) > 1


def _rank_of(candidate: RecipientCandidate) -> int:
    return _RANK[candidate.match_kind]


def _domain_of(address: str) -> str | None:
    return _folded(address.rpartition("@")[2]) or None


def _folded(text: str) -> str:
    return " ".join(text.casefold().split())


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_WORD.findall(text.casefold()))


def _when(received_at: datetime | None) -> datetime:
    if received_at is None:
        return _NEVER
    if received_at.tzinfo is None:
        return received_at.replace(tzinfo=UTC)
    return received_at


def _headers() -> HeadersCollection:
    headers = HeadersCollection()
    headers.add(*_QUERY_SOURCES)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Find Recipient",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_find_recipient(
        query: Annotated[
            str,
            Field(
                min_length=2,
                description=(
                    "The person to resolve — a name, alias, or partial address — exactly as "
                    + "the user wrote it."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=f"How many candidates to return, at most {MAX_RESULTS}.",
            ),
        ] = 20,
        client: GraphServiceClient = graph,
    ) -> RecipientCandidates:
        return await find_recipient(client, query=query, limit=limit)
