from dataclasses import dataclass
from typing import Annotated, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints

from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.resolution import BatchResolution, Candidate, Resolution

__all__ = [
    "BatchPartyResolution",
    "PartyCandidate",
    "PartyResolution",
    "PartyResolveItem",
    "QuickSearchOptions",
    "ResolvedParty",
    "SearchType",
]

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


class PartyAttributes(BaseModel):
    """Shape of a party resource's `attributes` in `search.py`'s JSON:API responses.

    A pydantic model (unlike the plain dataclasses below) because it's deserialized straight
    off the wire via `BackstopApiCollectionDocument[PartyAttributes]` /
    `BackstopApiResourceDocument[PartyAttributes]` — see `backstop_client.json_api`.
    `extra="ignore"` since only `id`/`name`/`label` (derived here) ever leave `search.py`.
    Names are stripped here so `search.py`'s display-name fallback can use plain truthiness
    checks instead of re-stripping at point of use.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    first_name: _StrippedStr | None = Field(
        default=None, validation_alias=AliasChoices("firstName", "first_name")
    )
    last_name: _StrippedStr | None = Field(
        default=None, validation_alias=AliasChoices("lastName", "last_name")
    )

    def display_name(self) -> str | None:
        if self.name:
            return self.name
        composed = " ".join(part for part in (self.first_name, self.last_name) if part)
        return composed or None



@dataclass(frozen=True)
class ResolvedParty:
    """A party identity after successful resolution."""

    id: str
    type: SearchType
    name: str | None = None


# Party resolution is one instance of the shared algebra in `resolution.py`: same result types,
# same ambiguity policy, same status strings as custom-field resolution.
type PartyCandidate = Candidate[ResolvedParty]
type PartyResolution = Resolution[ResolvedParty]
type BatchPartyResolution = BatchResolution[ResolvedParty]


@dataclass(frozen=True)
class PartyResolveItem:
    """One batch input: exactly one of `party_id` or `search` must be set.

    When `party_id` is set, optional `name` is passed through on the trusted-id short-circuit
    (no existence check). `name` is ignored when `search` is set.
    """

    party_id: str | None = None
    search: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        party_id = (self.party_id or "").strip() or None
        search = (self.search or "").strip() or None
        object.__setattr__(self, "party_id", party_id)
        object.__setattr__(self, "search", search)
        if (party_id is None) == (search is None):
            raise ValueError("Exactly one of party_id or search must be provided")


@dataclass(frozen=True)
class QuickSearchOptions:
    """Caller-overridable knobs for `GET /quick-search`.

    `full_email_match=None` means auto: true when the search looks like an email, else omit/false.
    `filter_type=None` means omit the param (API default). Pagination is first page only;
    `page[limit]` is aligned with `limit` by the search layer.
    """

    limit: int = 10
    full_email_match: bool | None = None
    show_all: bool = False
    enhance_search_types: bool = False
    filter_type: str | None = None
