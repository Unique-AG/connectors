from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.entities.names import NameRecordView
from polixis_mcp.contexts.freshness import Freshness
from polixis_mcp.contexts.risks import FLAGS_DESCRIPTION


class ProfileAlert(BaseModel):
    """A risk or status alert on the entity."""

    category: str | None = Field(
        description="Polixis's category: one of its own, such as regulatory (such as legal "
        "proceedings), closed (liquidated, dissolved or deceased), stateco (state-owned or a "
        "public body), restriction, sanctionterritory or listed, or one Polixis generated from "
        "a related party, ending in _RELATED, such as SANCTION_RELATED or PEP_RELATED."
    )
    message: str = Field(description="The alert, as Polixis words it.")


class SanctionListing(BaseModel):
    """One record of the entity on one sanctions list."""

    list_name: str = Field(
        description="The sanctions list. Polixis counts each authority's list once, such as one "
        "OFAC list for every OFAC programme; the programme is in `details`."
    )
    country: str | None = Field(description="ISO 3166-1 alpha-2 code of the listing authority.")
    status: str | None = Field(
        description="The record's Sanction Status detail, ACTIVE or DELISTED, as it gives it."
    )
    details: dict[str, list[str]] = Field(
        description="Every detail of the record, such as Program, Sanction type, Listing Date, "
        "Delisting Date, Sanction Status, Reference Number and Designation details."
    )


class PositionHeld(BaseModel):
    """A public or political position the person holds or held."""

    position: str = Field(description="The position.")
    institution: str | None = Field(
        description="The public body or institution where it is or was held."
    )
    start_date: str | None = Field(description="YYYY-MM-DD, YYYY-MM or YYYY, null if unknown.")
    end_date: str | None = Field(
        description="YYYY-MM-DD, YYYY-MM or YYYY; null if current or unknown."
    )
    remark: str | None = Field(description="A note Polixis adds, if any.")


class EntityProfile(BaseModel):
    """The requested sections of one entity's profile. A section not requested is null."""

    pid: str = Field(description="The pid looked up.")
    rejected: str | None = Field(
        default=None,
        description="Polixis's reason for rejecting the pid, such as an unknown id, which this "
        "MCP returns in place of the profile; null when it did not.",
    )
    names: list[str] | None = Field(default=None, description="Every name and spelling.")
    name_records: list[NameRecordView] | None = Field(
        default=None, description="Typed names, current, former and aliases."
    )
    identifiers: dict[str, list[str]] | None = Field(
        default=None, description="Identifiers by type, such as LEI, TIN or registration number."
    )
    countries: dict[str, list[str]] | None = Field(
        default=None,
        description="ISO 3166-1 alpha-2 codes by relation, such as country, "
        "countryCitizenship or countryJurisdiction: for a person, citizenship, residence and "
        "business ties; for an organization, where it is registered or operates.",
    )
    dates: dict[str, list[str]] | None = Field(
        default=None,
        description="Dates by kind, such as Date of Birth, Registration Date or Liquidation "
        "Date, as YYYY-MM-DD, YYYY-MM or YYYY.",
    )
    gender: str | None = Field(default=None, description="f, m or x, for a person.")
    legal_forms: list[str] | None = Field(default=None, description="Legal forms, in English.")
    economic_activities: list[str] | None = Field(
        default=None, description="Economic activity categories, in English."
    )
    addresses: list[str] | None = Field(default=None, description="Every address.")
    flags: list[str] | None = Field(default=None, description=FLAGS_DESCRIPTION)
    alerts: list[ProfileAlert] | None = Field(
        default=None,
        description="Polixis's risk and status alerts, its own and those it generated from "
        "related parties.",
    )
    sanction_statuses: dict[str, str] | None = Field(
        default=None, description="Sanctions list name to its status, ACTIVE or DELISTED."
    )
    sanctions: list[SanctionListing] | None = Field(
        default=None, description="Every sanctions record, one per list and listing."
    )
    positions: list[PositionHeld] | None = Field(
        default=None, description="Public and political positions held, for a PEP."
    )
    images: list[str] | None = Field(
        default=None,
        description="Image URLs: photos for a person, logos for an organization. Licensed data "
        "about real people: show them, do not store them.",
    )


class EntityProfiles(BaseModel):
    """The profiles of the entities asked for, in the order asked."""

    profiles: list[EntityProfile] = Field(description="One profile per distinct pid.")
    freshness: Freshness
