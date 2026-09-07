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

# Published party-selector contract. Party-scoped tools that require `search_type` reuse
# these strings so the model sees the same pairing on the way in and on the resolve echo.
RESOLVED_PARTY_ECHO_DESCRIPTION = (
    "The identity this call settled on. Echo `id` as `party_id` and `search_type` as "
    "`search_type` on the next party-scoped tool — two separate arguments. "
    "`party_id` alone is rejected. Never invent them."
)
REQUIRED_SEARCH_TYPE_DESCRIPTION = (
    "Required. Never omit, including when you already have a `party_id`. "
    "The argument is `search_type`. "
    "Which Backstop collection to resolve the party against — fold the caller's "
    "wording to one of the four. A company, firm, fund, institution, or manager is "
    "`organizations`; any human is `people`. Pick `contacts` or `employees` only "
    "when a prior resolve echoed one (echo it back — a contact or employee id is "
    "not a people id) or the caller clearly means an internal staff member."
)
PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION = (
    "Trusted Backstop Party ID from a prior resolve echo. The argument is `party_id` "
    "(not `entity_id` — that name is only on `get_activity_history` `request.type=next`). "
    "Always pass together with that echo's `search_type` as a separate argument — "
    "`party_id` alone is rejected. "
    "Never invent or guess. Exactly one of `party_id` or `search` must be provided."
)
SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION = (
    "Name or email to resolve when no trusted `party_id` is available. The argument "
    "is `search`. Always pass together with `search_type`. Exactly one of `party_id` "
    "or `search` must be provided."
)


class PartyCandidateResponse(CandidateResponse):
    """One ambiguous party match, returned so the model can ask the user to pick one.

    `search_type` is the candidate's own collection (which may differ from the requested
    scope when `enhance_search_types` returns a cross-type hit) — callers must pass it
    as `search_type` together with `id` as `party_id`, two separate arguments. `label`
    already names that collection in readable form (`Capstone (organization)`,
    `Jane Doe (person)`), so elicitation and this payload both show what the user is
    looking at.
    """

    label: str = Field(
        description=(
            "Display name and entity kind, e.g. 'Capstone (organization)' or "
            "'Jane Doe (person)'. The kind is organization, person, contact, or employee."
        )
    )
    id: str = Field(
        description=(
            "Backstop id of this candidate. Pass it as `party_id` together with this "
            "candidate's `search_type` as a separate argument — never invent one. "
            "`party_id` alone is rejected."
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
            "`search_type` as a separate `search_type` argument — never invent one. "
            "`party_id` alone is rejected on party-scoped tools."
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
    """Convert a non-`Resolved` `resolve_party` outcome into the standard tool response."""
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
    "PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION",
    "PartyAmbiguousResponse",
    "PartyBatchAmbiguousResponse",
    "PartyBatchResolvedResponse",
    "PartyBatchUnresolvedResponse",
    "PartyCandidateResponse",
    "REQUIRED_SEARCH_TYPE_DESCRIPTION",
    "RESOLVED_PARTY_ECHO_DESCRIPTION",
    "ResolvedPartyResponse",
    "SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION",
    "unresolved_parties_response",
    "unresolved_party_response",
]
