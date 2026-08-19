"""Party-shaped views of the shared resolution responses (`resolution.py`)."""

from collections.abc import Mapping

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


class PartyCandidateResponse(CandidateResponse):
    """One ambiguous party match, returned so the model can ask the user to pick one.

    `search_type` is the candidate's own collection (which may differ from the requested
    scope when `enhance_search_types` returns a cross-type hit) — callers must echo it
    verbatim with `id` when retrying as a trusted `party_id`. `label` already names that
    collection in readable form (`Capstone (organization)`, `Jane Doe (person)`), so
    elicitation and this payload both show what the user is looking at.
    """

    label: str = Field(
        description=(
            "Display name and entity kind, e.g. 'Capstone (organization)' or "
            "'Jane Doe (person)'. The kind is organization, person, contact, or employee."
        )
    )
    id: str = Field(
        description=(
            "Backstop id of this candidate. Echo it with `search_type` when retrying as "
            "`party_id` — never invent one."
        )
    )
    search_type: SearchType = Field(
        description=(
            "Collection this candidate belongs to: organizations, people, contacts, or "
            "employees. Echo it with `id` — a contact or employee id is not a people id."
        )
    )
    name: str | None = Field(
        default=None,
        description="Display name as Backstop stores it. Omitted when resolve did not learn one.",
    )


class ResolvedPartyResponse(OmitNoneModel):
    """The id/search_type/name a caller must pass back verbatim as a trusted `party_id` later.

    Never invent or guess these values — only return what a prior resolve call returned. Not a
    `CandidateResponse`: this is the single identity a call settled on, not one option among many.
    `name` is omitted when resolve did not learn one, matching the absent-vs-null rule the
    enclosing tools use.
    """

    id: str = Field(
        description=(
            "Backstop id of this party. Echo it with `search_type` as `party_id` later — "
            "never invent one."
        )
    )
    search_type: SearchType = Field(
        description=(
            "Collection this party belongs to: organizations, people, contacts, or employees. "
            "Echo it with `id` — a contact or employee id is not a people id."
        )
    )
    name: str | None = Field(
        default=None,
        description="Display name as Backstop stores it. Omitted when resolve did not learn one.",
    )


# Concrete parameterizations of the shared models. Plain assignments, not subclasses: pydantic
# resolves the subscript to a real model class, which is what FastMCP needs for output schemas.
PartyAmbiguousResponse = AmbiguousResponse[PartyCandidateResponse]
PartyBatchUnresolvedResponse = BatchUnresolvedResponse[PartyCandidateResponse]
PartyBatchResolvedResponse = BatchResolvedResponse[ResolvedPartyResponse]
PartyBatchAmbiguousResponse = BatchAmbiguousResponse[PartyCandidateResponse, ResolvedPartyResponse]


def party_response(
    party: ResolvedPartyDto,
    *,
    attributes: Mapping[str, object] | None = None,
) -> ResolvedPartyResponse:
    """Build a resolved-party response. When resolve left `name` blank and `attributes` are
    given, fill it from that record's `name` / `firstName`+`lastName`.
    """
    name = party.name
    if name is None and attributes is not None:
        name = PartyAttributes.model_validate(attributes).display_name()
    return ResolvedPartyResponse(id=party.id, search_type=party.search_type, name=name)


def party_candidate_response(candidate: PartyCandidate) -> PartyCandidateResponse:
    party = candidate.value
    return PartyCandidateResponse(
        key=candidate.key,
        label=candidate.label,
        id=party.id,
        search_type=party.search_type,
        name=party.name,
    )


def unresolved_party_response(
    result: Unresolved[ResolvedPartyDto],
) -> PartyAmbiguousResponse | NotFoundResponse:
    """Convert a non-`Resolved` `resolve_party` outcome into the standard tool response."""
    return unresolved_response(
        result,
        ambiguous_model=PartyAmbiguousResponse,
        to_candidate=party_candidate_response,
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
        to_candidate=party_candidate_response,
        to_resolved=party_response,
    )


__all__ = [
    "PartyAmbiguousResponse",
    "PartyBatchAmbiguousResponse",
    "PartyBatchResolvedResponse",
    "PartyBatchUnresolvedResponse",
    "PartyCandidateResponse",
    "ResolvedPartyResponse",
    "party_candidate_response",
    "party_response",
    "unresolved_parties_response",
    "unresolved_party_response",
]
