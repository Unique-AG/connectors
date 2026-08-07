"""Party-shaped views of the shared resolution responses (`resolution.py`)."""

from collections.abc import Mapping

from pydantic import BaseModel

from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver.types import (
    PartyAttributes,
    PartyCandidate,
    ResolvedParty,
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


class PartyCandidateResponse(CandidateResponse):
    """One ambiguous party match, returned so the model can ask the user to pick one."""

    id: str
    name: str | None = None


class ResolvedPartyResponse(BaseModel):
    """The id/search_type/name a caller must pass back verbatim as a trusted `party_id` later.

    Never invent or guess these values — only return what a prior resolve call returned. Not a
    `CandidateResponse`: this is the single identity a call settled on, not one option among many.
    """

    id: str
    search_type: SearchType
    name: str | None = None


# Concrete parameterizations of the shared models. Plain assignments, not subclasses: pydantic
# resolves the subscript to a real model class, which is what FastMCP needs for output schemas.
PartyAmbiguousResponse = AmbiguousResponse[PartyCandidateResponse]
PartyBatchUnresolvedResponse = BatchUnresolvedResponse[PartyCandidateResponse]
PartyBatchResolvedResponse = BatchResolvedResponse[ResolvedPartyResponse]
PartyBatchAmbiguousResponse = BatchAmbiguousResponse[PartyCandidateResponse, ResolvedPartyResponse]


def party_response(
    party: ResolvedParty,
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
        name=party.name,
    )


def unresolved_party_response(
    result: Unresolved[ResolvedParty],
) -> PartyAmbiguousResponse | NotFoundResponse:
    """Convert a non-`Resolved` `resolve_party` outcome into the standard tool response."""
    return unresolved_response(
        result,
        ambiguous_model=PartyAmbiguousResponse,
        to_candidate=party_candidate_response,
    )


def unresolved_parties_response(
    result: BatchAmbiguous[ResolvedParty],
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
