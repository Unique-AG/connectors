"""Party-shaped views of the shared resolution responses (`resolution.py`)."""

from collections.abc import Mapping
from typing import Self

from pydantic import Field

from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver.api_responses import PartyAttributes
from backstop_mcp.features.party_resolver.internal_dto import (
    PartyCandidate,
    ResolvedPartyDto,
)
from backstop_mcp.features.resolution import (
    AmbiguousResponse,
    BatchAmbiguous,
    BatchAmbiguousResponse,
    BatchResolvedResponse,
    BatchUnresolvedResponse,
    CandidateResponse,
    NotFoundResponse,
    Unresolved,
    batch_ambiguous_response,
    unresolved_response,
)
from backstop_mcp.models import OmitNoneModel

# Published party-selector contract. Tools whose `search_type` is required reuse the
# `*_REQUIRES_SEARCH_TYPE_*` strings; tools that default `search_type` use the
# `*_DEFAULT_SEARCH_TYPE_*` ones, so neither tells the model something the schema contradicts.
RESOLVED_PARTY_ECHO_DESCRIPTION = (
    "The identity this call settled on. Echo `id` as `party_id` and `search_type` as "
    "`search_type` on the next party-scoped tool — two separate arguments. "
    "Never invent them."
)
REQUIRED_SEARCH_TYPE_DESCRIPTION = (
    "Required. Never omit, including when you already have a `party_id`. "
    "Which Backstop collection to resolve the party against — fold the caller's "
    "wording to one of the four. A company, firm, fund, institution, or manager is "
    "`organizations`; any human is `people`. Pick `contacts` or `employees` only "
    "when a prior tool returned one with the id (echo it back — a contact or employee "
    "id is not a people id)."
)
PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION = (
    "Trusted Backstop party id (an organization, person, contact, or employee) from a "
    "prior resolve, search, or party result. Not an account, product, opportunity, task, "
    "or activity id. "
    "Always pass together with the `search_type` that came with it, as a "
    "separate argument — `party_id` alone is rejected. "
    "Never invent or guess. Exactly one of `party_id` or `search` must be provided."
)
SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION = (
    "Name or email to resolve when no trusted `party_id` is available. "
    "Always pass together with `search_type`. Exactly one of `party_id` "
    "or `search` must be provided."
)
PARTY_ID_DEFAULT_SEARCH_TYPE_DESCRIPTION = (
    "Trusted Backstop party id (an organization, person, contact, or employee) from a "
    "prior resolve, search, or party result. Not an account, product, opportunity, task, "
    "or activity id. "
    "Echo the `search_type` that came with it when it is not this tool's "
    "default. Never invent or guess. Exactly one of `party_id` or `search` must be provided."
)
SEARCH_DEFAULT_SEARCH_TYPE_DESCRIPTION = (
    "Name or email to resolve when no trusted `party_id` is available. "
    "Exactly one of `party_id` or `search` must be provided."
)


class PartyCandidateResponse(CandidateResponse):
    """One ambiguous party match, returned so the model can ask the user to pick one.

    `search_type` is the candidate's own collection (which may differ from the requested
    scope when `enhance_search_types` returns a cross-type hit) — callers must pass it
    as `search_type` together with `id` as `party_id`, two separate arguments. `label`
    already names that collection in readable form (`Northwind (organization)`,
    `Jane Doe (person)`), so elicitation and this payload both show what the user is
    looking at.
    """

    label: str = Field(
        description=(
            "Display name and entity kind, e.g. 'Northwind (organization)' or "
            "'Jane Doe (person)'. The kind is organization, person, contact, or employee."
        )
    )
    id: str = Field(
        description=(
            "Backstop id of this candidate. Pass it as `party_id` together with this "
            "candidate's `search_type` as a separate argument — never invent one."
        )
    )
    search_type: SearchType = Field(
        description=(
            "Collection this candidate belongs to: organizations, people, contacts, or "
            "employees. Pass it as `search_type` together with `id` as `party_id` — two "
            "separate arguments. A contact or employee id is not a people id."
        )
    )
    name: str | None = Field(
        default=None,
        description="Display name as Backstop stores it. Omitted when resolve did not learn one.",
    )

    @classmethod
    def from_candidate(cls, candidate: PartyCandidate) -> Self:
        party = candidate.value
        return cls(
            key=candidate.key,
            label=candidate.label,
            id=party.id,
            search_type=party.search_type,
            name=party.name,
        )


class ResolvedPartyResponse(OmitNoneModel):
    """The id and search_type a caller must pass back as two separate tool arguments later.

    Never invent or guess these values — only return what a prior resolve call returned. Not a
    `CandidateResponse`: this is the single identity a call settled on, not one option among many.
    `name` is omitted when resolve did not learn one, matching the absent-vs-null rule the
    enclosing tools use.
    """

    id: str = Field(
        description=(
            "Backstop id of this party. Pass it as `party_id` together with this object's "
            "`search_type` as a separate `search_type` argument — never invent one."
        )
    )
    search_type: SearchType = Field(
        description=(
            "Collection this party belongs to: organizations, people, contacts, or employees. "
            "Pass it as `search_type` together with `id` as `party_id` — two separate "
            "arguments. A contact or employee id is not a people id."
        )
    )
    name: str | None = Field(
        default=None,
        description="Display name as Backstop stores it. Omitted when resolve did not learn one.",
    )

    @classmethod
    def from_party(
        cls,
        party: ResolvedPartyDto,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> Self:
        """Build a resolved-party response. When resolve left `name` blank and `attributes` are
        given, fill it from that record's `name` / `firstName`+`lastName`.
        """
        name = party.name
        if name is None and attributes is not None:
            name = PartyAttributes.model_validate(attributes).display_name()
        return cls(id=party.id, search_type=party.search_type, name=name)


# Concrete parameterizations of the shared models. Plain assignments, not subclasses: pydantic
# resolves the subscript to a real model class, which is what FastMCP needs for output schemas.
PartyAmbiguousResponse = AmbiguousResponse[PartyCandidateResponse]
PartyBatchUnresolvedResponse = BatchUnresolvedResponse[PartyCandidateResponse]
PartyBatchResolvedResponse = BatchResolvedResponse[ResolvedPartyResponse]
PartyBatchAmbiguousResponse = BatchAmbiguousResponse[PartyCandidateResponse, ResolvedPartyResponse]


def unresolved_party_response(
    result: Unresolved[ResolvedPartyDto],
) -> PartyAmbiguousResponse | NotFoundResponse:
    """Convert a non-`Resolved` party resolution into the standard tool response."""
    return unresolved_response(
        result,
        ambiguous_model=PartyAmbiguousResponse,
        to_candidate=PartyCandidateResponse.from_candidate,
    )


def unresolved_parties_response(
    result: BatchAmbiguous[ResolvedPartyDto],
) -> PartyBatchAmbiguousResponse:
    """One combined payload for a batch where at least one party didn't resolve."""
    return batch_ambiguous_response(
        result,
        batch_model=PartyBatchAmbiguousResponse,
        unresolved_model=PartyBatchUnresolvedResponse,
        resolved_model=PartyBatchResolvedResponse,
        to_candidate=PartyCandidateResponse.from_candidate,
        to_resolved=ResolvedPartyResponse.from_party,
    )


__all__ = [
    "PARTY_ID_DEFAULT_SEARCH_TYPE_DESCRIPTION",
    "PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION",
    "PartyAmbiguousResponse",
    "PartyBatchAmbiguousResponse",
    "PartyBatchResolvedResponse",
    "PartyBatchUnresolvedResponse",
    "PartyCandidateResponse",
    "REQUIRED_SEARCH_TYPE_DESCRIPTION",
    "RESOLVED_PARTY_ECHO_DESCRIPTION",
    "ResolvedPartyResponse",
    "SEARCH_DEFAULT_SEARCH_TYPE_DESCRIPTION",
    "SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION",
    "unresolved_parties_response",
    "unresolved_party_response",
]
