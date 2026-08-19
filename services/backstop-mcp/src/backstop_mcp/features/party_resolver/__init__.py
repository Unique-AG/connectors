from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver.api_responses import PartyAttributes
from backstop_mcp.features.party_resolver.internal_dto import (
    BatchPartyResolution,
    PartyCandidate,
    PartyResolution,
    PartyResolveItemDto,
    QuickSearchOptionsDto,
    ResolvedPartyDto,
)
from backstop_mcp.features.party_resolver.resolve import resolve_parties, resolve_party
from backstop_mcp.features.party_resolver.responses import (
    PartyAmbiguousResponse,
    PartyCandidateResponse,
    ResolvedPartyResponse,
    party_candidate_response,
    party_response,
    unresolved_parties_response,
    unresolved_party_response,
)

ResolvedParty = ResolvedPartyDto
PartyResolveItem = PartyResolveItemDto
QuickSearchOptions = QuickSearchOptionsDto

__all__ = [
    "BatchPartyResolution",
    "PartyAmbiguousResponse",
    "PartyCandidate",
    "PartyAttributes",
    "PartyCandidateResponse",
    "PartyResolution",
    "PartyResolveItemDto",
    "QuickSearchOptionsDto",
    "ResolvedPartyDto",
    "ResolvedPartyResponse",
    "SearchType",
    "party_candidate_response",
    "party_response",
    "resolve_parties",
    "resolve_party",
    "unresolved_parties_response",
    "unresolved_party_response",
]
