"""`outlook_find_recipient` — the address a name sends from, so a draft is not addressed to a guess.

Two indexes, asked one after the other, and neither of them is a directory lookup.

**A person search is fuzzy by default, and Microsoft does not publish how fuzzy.** `$search="tiler"`
returns Tyler: a row Graph is pleased with rather than the person the user named. A model handed a
list takes row one, and at that point the draft is addressed to the wrong human at an address that
delivers. So every row carries a `match_kind` computed *here*, by comparing the row against the
query as it was sent, and `ambiguous` is set whenever more than one row shares the best one. No row
is ever chosen for the caller.

**`relevanceScore` is not in the answer, and that is the point.** Microsoft documents it as "a sort
key, in relation to the other returned results" — a number whose whole meaning is the rest of this
one page — and under `$search` Graph returns it negative. A model shown a score ranks on it, which
is the ranking this tool exists to refuse. It is left out of the answer model entirely rather than
returned with a warning attached.

**The second index is written by strangers.** `participants` is documented as "the from, to, cc, and
bcc fields of an email message, specified as an SMTP address, display name, or alias", so it matches
display names — and a sender chooses their own. Anyone who has mailed this mailbox once can put
another person's name beside their own address. Those rows say `source: "mailbox"`, and they are
evidence that correspondence happened, never evidence of who somebody is.

**An address is never `userPrincipalName`.** A guest's sign-in name carries `#EXT#` and bounces
while their real address sits elsewhere, so the address comes off `scoredEmailAddresses[].address`
on the people path and off `emailAddress.address` on the mailbox one. The sign-in name is still
*asked* for, because a caller who typed one deserves an `exact` match — it is matched against and
never answered with.
"""

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

# `People.Read` for the relevance list, `Mail.Read` for the fallback, `User.Read` for the signed-in
# user every row's `external` is decided against. `User.Read` is named rather than assumed: the
# token this tool is handed is exchanged for exactly the permissions declared here, so an undeclared
# one is a 403 on a call nothing else in the tool touches.
GRAPH_PERMISSIONS: tuple[str, ...] = ("People.Read", "Mail.Read", identity.GRAPH_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "Tyler"}

MAX_RESULTS = 50

# TRAP: written out in plain ASCII on purpose. Microsoft's documentation renders this header with
# typographic hyphens, and a header pasted from the page is one Graph does not recognise — it
# answers 200 with the directory half of the index silently missing, never an error.
_QUERY_SOURCES = ("X-PeopleQuery-QuerySources", "Mailbox,Directory")

# Microsoft documents `$search` on this collection as matching `displayName` and `emailAddresses`.
# `userPrincipalName` is projected to be compared against, never to be answered with.
_PERSON_FIELDS = (
    "displayName",
    "scoredEmailAddresses",
    "userPrincipalName",
    "personType",
    "jobTitle",
    "department",
)

_PARTICIPANT_FIELDS = ("from", "toRecipients", "ccRecipients", "receivedDateTime")

# The fallback reads messages to harvest people out of them, so the window is messages and not
# people: one correspondent commonly owns twenty of these rows, and `limit` bounds the answer.
_PARTICIPANT_MESSAGES = 50

type MatchKind = Literal["exact", "token", "fuzzy"]
type RecipientKind = Literal["person", "group", "room"]
type RecipientSource = Literal["people", "mailbox"]
type Outcome = Literal["match", "no_match"]

type _PeopleQuery = PeopleRequestBuilder.PeopleRequestBuilderGetQueryParameters
type _MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

# Best first. Ordering the answer by this is a ranking this file can explain; ordering it by what
# Graph returned would be `relevanceScore` reaching the model through the door it was refused at.
_RANK: Mapping[MatchKind, int] = {"exact": 0, "token": 1, "fuzzy": 2}

# Word characters minus the underscore, so `tyler_nguyen` and `tyler.nguyen` yield the same two
# tokens. Unicode-aware: a name is not spelled in ASCII by necessity.
_WORD = re.compile(r"[^\W_]+")

_NEVER = datetime.min.replace(tzinfo=UTC)

_DESCRIPTION = """\
Resolve a person's name to the email address they send from, before addressing a draft to a guess. \
Answers candidates for a human to confirm — never an address to send to unprompted, and never a \
row to pick because it came first. Microsoft's person index matches fuzzily, so `tiler` returns \
Tyler: read `match_kind` on every row, and treat `ambiguous` as "ask the user which one". An empty \
answer means this user's index holds nobody by that name, which is not the same as nobody \
existing. Returns each candidate's address, display name, match kind, type, whether they are \
outside the user's own domain, job title and department.\
"""

_NO_QUERY = (
    "outlook_find_recipient needs a name, an alias or an address to look for, and this query "
    + "carries no word to match on. Graph answers an empty person search with an arbitrary slice "
    + "of the user's relevance list, which is a sample of who they know and not an answer."
)


class RecipientCandidate(BaseModel):
    """One address a name could mean, with what is known about how well it means it."""

    address: str = Field(
        description=(
            "The SMTP address to put on a draft. Taken from the address list Microsoft returns "
            + "for the person, never from their sign-in name: a guest's sign-in name carries "
            + "`#EXT#` and bounces while this address delivers."
        )
    )
    display_name: str | None = Field(
        description=(
            "The name shown for this address. On a `mailbox` row it is a name the sender chose "
            + "for themselves, so it is a claim rather than a directory fact. Null when Graph "
            + "recorded none."
        )
    )
    match_kind: MatchKind = Field(
        description=(
            "How this row compares with the query as it was sent, computed here and not by "
            + "Microsoft. `exact`: the query is the whole display name, the whole address, its "
            + "local part or the sign-in name. `token`: every word of the query is a whole word "
            + "of the name or of the address's local part. `fuzzy`: Microsoft matched it and "
            + "nothing about the row says why — `tiler` lands here against Tyler. Never draft to "
            + "a `fuzzy` row without asking."
        )
    )
    kind: RecipientKind | None = Field(
        description=(
            "What the address belongs to: `person`, `group` for a distribution list or a "
            + "Microsoft 365 group, `room` for a bookable resource such as a meeting room or "
            + "equipment. Null when Graph reported no type, which is every `mailbox` row: an "
            + "Exchange recipient carries none."
        )
    )
    external: bool | None = Field(
        description=(
            "True when the address's domain differs from the signed-in user's own. Worth saying "
            + "out loud before a draft goes out. Null when the signed-in user has no address to "
            + "compare against, or the candidate's has no domain."
        )
    )
    job_title: str | None = Field(
        description=(
            "The job title from the directory, when it records one. Use it to tell two people of "
            + "the same name apart. Null on every `mailbox` row."
        )
    )
    department: str | None = Field(
        description=(
            "The department from the directory, when it records one. Null on every `mailbox` row."
        )
    )
    source: RecipientSource = Field(
        description=(
            "Which index answered. `people` is Microsoft's relevance list for this user, drawn "
            + "from their mailbox and the directory. `mailbox` is a fallback over the messages "
            + "this user has exchanged, and its display names are written by whoever sent the "
            + "mail — a sender chooses their own name, so a `mailbox` row can carry one person's "
            + "name beside another person's address. Confirm a `mailbox` row against a human."
        )
    )
    ever_corresponded: bool = Field(
        description=(
            "True when this address was found on a message in this user's own mailbox, so at "
            + "least one message has passed between them. False means that was not established "
            + "here — it is not evidence that they have never corresponded."
        )
    )


class RecipientCandidates(BaseModel):
    """Who the query could mean, and how sure of it this connector is allowed to be."""

    outcome: Outcome = Field(
        description=(
            "`match` when at least one candidate came back, `no_match` when neither index held "
            + "anybody. `no_match` is not proof the person does not exist. It means they are not "
            + "in this user's index, and there are at least five ways for that to be true: the "
            + "two have never corresponded; the person is not on this user's relevance list; an "
            + "information barrier separates them; the person is hidden from the address list; "
            + "or they joined too recently to be indexed. Say that rather than reporting that no "
            + "such person exists, and ask the user for the address."
        )
    )
    query: str = Field(
        description=(
            "The query exactly as it was sent, so a `no_match` can be quoted back to the user "
            + "and a spelling can be corrected without guessing what was asked."
        )
    )
    candidates: list[RecipientCandidate] = Field(
        description=(
            "Candidates, strongest `match_kind` first and Microsoft's own order kept within each "
            + "kind. First is not chosen: it is only the strongest kind this search found, and "
            + "the strongest kind of a bad search is still a bad answer."
        )
    )
    ambiguous: bool = Field(
        description=(
            "True when more than one candidate shares the best `match_kind`, so the answer names "
            + "no single person. Put the choice to the user rather than resolving it — two people "
            + "of one name is the ordinary case, not the strange one."
        )
    )


@dataclass(frozen=True, slots=True)
class _Caller:
    """The signed-in user, as the two things every row is judged against."""

    address: str | None
    domain: str | None

    @classmethod
    def of(cls, user: User) -> "_Caller":
        # `mail` first: `userPrincipalName` is a sign-in name on a possibly different domain, and
        # get_me says the same thing to the model.
        address = user.mail or user.user_principal_name
        return cls(address=address, domain=None if address is None else _domain_of(address))


async def find_recipient(
    client: GraphServiceClient, *, query: str, limit: int
) -> RecipientCandidates:
    """Resolve `query` against the people index, and against the mailbox only if that found nobody.

    The mailbox call is skipped whenever the people index answered at all, including with rows this
    file grades `fuzzy`: a second index cannot improve an answer, only lengthen it.
    """
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
    """Everyone on a message this query matched, minus the user themselves and the bystanders.

    `participants` matches whole messages, so every recipient of a hit arrives with the person
    asked for. The query has to be found again in the row, or a mail to a mailing list would answer
    with the mailing list.
    """
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
    """One row per address, the strongest grading of it, most recently seen first."""
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
    """None for a person Graph returned no address for, which no draft can be addressed to."""
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
    """None for the signed-in user, for a bystander on the same message, and for a missing address.

    A row is kept only when the query is still findable in what it says. Graph matched the
    *message*, and everyone copied on it arrived with the person actually asked for.
    """
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
    """`from`, `to` and `cc` as one collection. Bcc is not projectable on a received message."""
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
    """The first address Microsoft listed for the person, and never their sign-in name.

    The order is Microsoft's own relevance order and the score behind it is deliberately not read:
    it is relative to the other rows of the same response, so it says nothing about one person's
    two addresses that "the first one" does not already say.
    """
    for scored in addresses or []:
        if scored.address:
            return scored.address
    return None


def _kind_of(person_type: PersonType | None) -> RecipientKind | None:
    """Graph's two-part `personType` as the one word a caller needs."""
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
    """How well the row answers the query, decided here because Graph will not say.

    The sign-in name counts towards `exact` and not towards `token`: its own tokens are the tenant's
    domain and, for a guest, the word `EXT`, none of which is anybody's name.
    """
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
    """True when the best grading is shared, which is the case this tool refuses to break."""
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
    """A naive datetime would not compare against an aware one, and Graph has answered with both."""
    if received_at is None:
        return _NEVER
    if received_at.tzinfo is None:
        return received_at.replace(tzinfo=UTC)
    return received_at


def _headers() -> HeadersCollection:
    """Built per request: adding to the shared default collection would affect every Graph call."""
    headers = HeadersCollection()
    headers.add(*_QUERY_SOURCES)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    # Closes over `transport` here; the default below holds this name, not a call (ruff's B008).
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
                    "The person to resolve: a name, a first name, an alias or a partial address. "
                    + "Pass what the user actually wrote — the answer grades every row against "
                    + "this exact text, so a query you tidied up first grades a row you invented."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=(
                    f"How many candidates to return, at most {MAX_RESULTS}. Raising it does not "
                    + "improve the top row; it lengthens the tail of fuzzy ones."
                ),
            ),
        ] = 20,
        client: GraphServiceClient = graph,
    ) -> RecipientCandidates:
        return await find_recipient(client, query=query, limit=limit)
