"""Internal listing result for people linked to one organization."""

from dataclasses import dataclass

from backstop_mcp.features.data_hygiene import EmploymentLinkResponse
from backstop_mcp.features.includes import ContactCardResponse


@dataclass(frozen=True)
class PersonAtOrganization:
    """One person the index tied to this organization, plus their `/employees` contact card."""

    employment: EmploymentLinkResponse
    card: ContactCardResponse | None = None


@dataclass(frozen=True)
class OrgPeopleListing:
    people: tuple[PersonAtOrganization, ...]
    former_omitted: int = 0
    people_omitted: int = 0
