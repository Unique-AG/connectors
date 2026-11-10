from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.entities.names import NameRecordView


class ProfileAlert(BaseModel):
    """A risk or status alert on the entity."""

    category: str | None = Field(
        description="Such as SANCTION, RESTRICTION, STATECO, REGULATORY or LISTED."
    )
    message: str = Field(description="The alert, as Polixis words it.")


class SanctionListing(BaseModel):
    """One record of the entity on one sanctions list."""

    list_name: str = Field(description="The sanctions list.")
    country: str | None = Field(description="ISO 3166-1 alpha-2 code of the listing authority.")
    status: str | None = Field(description="ACTIVE or DELISTED, as the record gives it.")
    details: dict[str, list[str]] = Field(
        description="Every detail of the record, such as Program, Justification and Source."
    )


class PositionHeld(BaseModel):
    """A public or political position the person holds or held."""

    position: str = Field(description="The position.")
    institution: str | None = Field(description="Where the position is held.")
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
        description="Why Polixis rejected the pid, such as an unknown id; null when it did not.",
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
        "countryCitizenship or countryJurisdiction.",
    )
    dates: dict[str, list[str]] | None = Field(
        default=None,
        description="Dates by kind, such as Date of Birth or Registration Date, as YYYY-MM-DD, "
        "YYYY-MM or YYYY.",
    )
    gender: str | None = Field(default=None, description="f, m or x, for a person.")
    legal_forms: list[str] | None = Field(default=None, description="Legal forms, in English.")
    economic_activities: list[str] | None = Field(
        default=None, description="Economic activity categories, in English."
    )
    addresses: list[str] | None = Field(default=None, description="Every address.")
    flags: list[str] | None = Field(
        default=None, description="Such as SANCTION, PEP, FORMER_PEP or REP."
    )
    alerts: list[ProfileAlert] | None = Field(default=None, description="Risk and status alerts.")
    sanction_statuses: dict[str, str] | None = Field(
        default=None, description="Sanctions list name to its status, ACTIVE or DELISTED."
    )
    sanctions: list[SanctionListing] | None = Field(
        default=None, description="Every sanctions record, one per list and listing."
    )
    positions: list[PositionHeld] | None = Field(
        default=None, description="Public and political positions held, for a PEP."
    )


class EntityProfiles(BaseModel):
    """The profiles of the entities asked for, in the order asked."""

    profiles: list[EntityProfile] = Field(description="One profile per distinct pid.")
