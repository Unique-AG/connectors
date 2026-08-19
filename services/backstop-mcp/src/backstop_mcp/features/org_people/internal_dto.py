"""Internal listing result for people linked to one organization."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from backstop_mcp.features.data_hygiene import EmploymentLinkResponse
from backstop_mcp.features.includes import ContactCardResponse

__all__ = ["OrgPeopleListingDto", "PersonAtOrganizationDto"]


class PersonAtOrganizationDto(BaseModel):
    """One person the index tied to this organization, plus their `/employees` contact card."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    employment: EmploymentLinkResponse
    card: ContactCardResponse | None = None


class OrgPeopleListingDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    people: tuple[PersonAtOrganizationDto, ...]
    former_omitted: int = 0
    people_omitted: int = 0
