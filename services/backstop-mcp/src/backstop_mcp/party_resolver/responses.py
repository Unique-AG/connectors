from typing import Literal

from pydantic import BaseModel

from backstop_mcp.party_resolver.types import NeedsDisambiguation, NotFound, SearchType


class CandidateEcho(BaseModel):
    """One ambiguous match, echoed back to the LLM so it can ask the user to pick one."""

    id: str
    name: str | None
    label: str


class ResolvedPartyEcho(BaseModel):
    """The id/type/name a caller must pass back verbatim as a trusted `party_id` later.

    Never invent or guess these values — only echo what a prior resolve call returned.
    """

    id: str
    type: SearchType
    name: str | None


class NeedsDisambiguationResponse(BaseModel):
    """A resolve-based tool's response when a search matched 2+ candidates."""

    status: Literal["needs_disambiguation"] = "needs_disambiguation"
    search: str
    search_type: SearchType
    candidates: list[CandidateEcho]


class NotFoundResponse(BaseModel):
    """A resolve-based tool's response when a search matched zero candidates."""

    status: Literal["not_found"] = "not_found"
    search: str
    search_type: SearchType


def early_exit_response(
    result: NeedsDisambiguation | NotFound,
) -> NeedsDisambiguationResponse | NotFoundResponse:
    """Convert a non-`Resolved` `resolve_party` outcome into the standard tool response.

    Callers short-circuit on this before doing any tool-specific fetch: there's nothing
    left to look up until the caller either supplies a trusted `party_id` from
    `candidates` or narrows `search`.
    """
    if isinstance(result, NeedsDisambiguation):
        return NeedsDisambiguationResponse(
            search=result.search,
            search_type=result.search_type,
            candidates=[
                CandidateEcho(id=candidate.id, name=candidate.name, label=candidate.label)
                for candidate in result.candidates
            ],
        )
    return NotFoundResponse(search=result.search, search_type=result.search_type)
