"""Party targeting shared by `log_activity` and `attach_file` inputs."""

from typing import Annotated, Self

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    REQUIRED_SEARCH_TYPE_DESCRIPTION,
    SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION,
)

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_SECONDARY_SEARCH_TYPE_DESCRIPTION = (
    "Collection for `secondary_party_id` when linking a second party (a person at an "
    "organisation). Pass together with `secondary_party_id`. Omit both when there is no "
    "secondary party."
)
_SECONDARY_PARTY_ID_DESCRIPTION = (
    "Trusted Backstop id of a second party to link (linkedResources / secondaryRegarding), "
    "for a person-at-organisation case. Pass together with `secondary_search_type`. "
    "Do not repeat the parent party. Never invent or guess."
)


class PartyTargetInput(BaseModel):
    """Exactly one of `party_id` or `search`, the way `get_tasks_for_party` does."""

    search_type: SearchType = Field(description=REQUIRED_SEARCH_TYPE_DESCRIPTION)
    party_id: _NonEmptyStr | None = Field(
        default=None, description=PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )
    search: _NonEmptyStr | None = Field(
        default=None, description=SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )

    @field_validator("party_id", "search", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> Self:
        if (self.party_id is None) == (self.search is None):
            raise ValueError("Exactly one of party_id or search must be provided")
        if self.party_id is not None and "/" in self.party_id:
            raise ValueError(f"party_id {self.party_id!r} must not contain '/'")
        return self


class SecondaryPartyInput(BaseModel):
    """Optional second party for linkedResources / secondaryRegarding (parent excluded later)."""

    secondary_search_type: SearchType | None = Field(
        default=None, description=_SECONDARY_SEARCH_TYPE_DESCRIPTION
    )
    secondary_party_id: _NonEmptyStr | None = Field(
        default=None, description=_SECONDARY_PARTY_ID_DESCRIPTION
    )

    @field_validator("secondary_party_id", mode="before")
    @classmethod
    def _blank_secondary_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _secondary_pairing(self) -> Self:
        if (self.secondary_party_id is None) != (self.secondary_search_type is None):
            raise ValueError("secondary_party_id and secondary_search_type must be passed together")
        if self.secondary_party_id is not None and "/" in self.secondary_party_id:
            raise ValueError(f"secondary_party_id {self.secondary_party_id!r} must not contain '/'")
        return self
