from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver.require_exactly_one_party_selector import (
    blank_to_none,
    require_exactly_one_party_selector,
)
from backstop_mcp.features.resolution import BatchResolution, Candidate, Resolution
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "BatchPartyResolution",
    "PartyCandidate",
    "PartyResolution",
    "PartyResolveItemDto",
    "QuickSearchOptionsDto",
    "ResolvedPartyDto",
]


class ResolvedPartyDto(BaseModel):
    """A party identity after successful resolution."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    search_type: SearchType
    name: str | None = None


# Party resolution is an instance of the shared algebra in `resolution.py`: same result types,
# same ambiguity policy, same status strings.
type PartyCandidate = Candidate[ResolvedPartyDto]
type PartyResolution = Resolution[ResolvedPartyDto]
type BatchPartyResolution = BatchResolution[ResolvedPartyDto]


class PartyResolveItemDto(BaseModel):
    """One batch input: exactly one of `party_id` or `search` must be set.

    When `party_id` is set, optional `name` is passed through on the trusted-id short-circuit
    (no existence check). `name` is ignored when `search` is set.

    `party_id` is interpolated into a Backstop path (e.g. `/organizations/{id}`) after
    `quote(..., safe='')`; rejecting `/` here keeps defence-in-depth consistent for every entry
    point that builds a `PartyResolveItemDto`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    party_id: NonEmptyStr | None = None
    search: NonEmptyStr | None = None
    # Same blank→None coercion as the selectors: whitespace-only must not count as "known"
    # and skip `confirm_name` / attribute backfill.
    name: NonEmptyStr | None = None

    @field_validator("party_id", "search", "name", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return blank_to_none(value)

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> Self:
        require_exactly_one_party_selector(party_id=self.party_id, search=self.search)
        return self


class QuickSearchOptionsDto(BaseModel):
    """Caller-overridable knobs for `GET /quick-search`.

    `full_email_match=None` means auto: true when the search looks like an email, else omit/false.
    `filter_type=None` means omit the param (API default). Pagination is first page only;
    `page[limit]` is aligned with `limit` by the search layer.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    # Upper bound matches Backstop's documented max page size for report-sized reads.
    limit: int = Field(default=10, gt=0, le=500)
    full_email_match: bool | None = None
    show_all: bool = False
    enhance_search_types: bool = False
    filter_type: str | None = None
