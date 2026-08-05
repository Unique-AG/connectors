"""Party-shaped views of the shared resolution responses (`resolution.py`)."""

from pydantic import BaseModel

from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver.types import PartyCandidate, ResolvedParty
from backstop_mcp.features.resolution import (
    AmbiguousResponse,
    BatchAmbiguous,
    BatchAmbiguousResponse,
    BatchResolvedEcho,
    BatchUnresolvedEcho,
    CandidateEcho,
    NotFoundResponse,
    Unresolved,
    batch_ambiguous_response,
    unresolved_response,
)


class PartyCandidateEcho(CandidateEcho):
    """One ambiguous party match, echoed back so the model can ask the user to pick one."""

    id: str
    name: str | None = None


class ResolvedPartyEcho(BaseModel):
    """The id/type/name a caller must pass back verbatim as a trusted `party_id` later.

    Never invent or guess these values — only echo what a prior resolve call returned. Not a
    `CandidateEcho`: this is the single identity a call settled on, not one option among many.
    """

    id: str
    type: SearchType
    name: str | None = None


# Concrete parameterizations of the shared models. Plain assignments, not subclasses: pydantic
# resolves the subscript to a real model class, which is what FastMCP needs for output schemas.
PartyAmbiguousResponse = AmbiguousResponse[PartyCandidateEcho]
PartyBatchUnresolvedEcho = BatchUnresolvedEcho[PartyCandidateEcho]
PartyBatchResolvedEcho = BatchResolvedEcho[ResolvedPartyEcho]
PartyBatchAmbiguousResponse = BatchAmbiguousResponse[PartyCandidateEcho, ResolvedPartyEcho]


def party_echo(party: ResolvedParty) -> ResolvedPartyEcho:
    return ResolvedPartyEcho(id=party.id, type=party.type, name=party.name)


def party_candidate_echo(candidate: PartyCandidate) -> PartyCandidateEcho:
    party = candidate.value
    return PartyCandidateEcho(
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
        to_echo=party_candidate_echo,
    )


def unresolved_parties_response(
    result: BatchAmbiguous[ResolvedParty],
) -> PartyBatchAmbiguousResponse:
    """One combined payload for a batch where at least one party didn't resolve."""
    return batch_ambiguous_response(
        result,
        batch_model=PartyBatchAmbiguousResponse,
        unresolved_model=PartyBatchUnresolvedEcho,
        resolved_model=PartyBatchResolvedEcho,
        to_echo=party_candidate_echo,
        to_resolved=party_echo,
    )


__all__ = [
    "PartyAmbiguousResponse",
    "PartyBatchAmbiguousResponse",
    "PartyBatchResolvedEcho",
    "PartyBatchUnresolvedEcho",
    "PartyCandidateEcho",
    "ResolvedPartyEcho",
    "party_candidate_echo",
    "party_echo",
    "unresolved_parties_response",
    "unresolved_party_response",
]
