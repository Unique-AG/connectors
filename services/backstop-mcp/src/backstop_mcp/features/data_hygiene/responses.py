"""Tool-facing responses for provenance and employment links."""

from datetime import date
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.data_hygiene.api_responses import CleanStr
from backstop_mcp.features.data_hygiene.internal_dto import (
    DepartedEmploymentDto,
    DepartureSignal,
)
from backstop_mcp.models import OmitNoneModel

type EmploymentLinkStatus = Literal["current", "former"]


class AsOfResponse(OmitNoneModel):
    """Plain provenance from a Backstop record. No staleness verdict attached."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    modified_timestamp: CleanStr = Field(
        default=None,
        description=(
            "When the record was last saved in Backstop. Omitted when unknown. Relay this; "
            "do not treat age as a staleness verdict."
        ),
    )
    modified_by: CleanStr = Field(
        default=None,
        description="Who last saved the record, as Backstop stores it. Omitted when unknown.",
    )


class DepartedContactResponse(BaseModel):
    """Hard signal that employment at an organization has ended. Always relay this flag."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    # Typed as the enum, not `str`, so the tool schema publishes the two possible values instead
    # of a free-form string the caller has to read a description to interpret.
    signal: DepartureSignal = Field(
        description=(
            "Which evidence this rests on: 'former_relationship_type' (the CRM links the person"
            " to the organization as a past employee) or 'end_date_passed'."
        )
    )
    organization_id: str = Field(
        description="Backstop id of the organization this employment has ended at."
    )
    organization_type: str = Field(
        description="Collection of that organization, typically 'organizations'."
    )
    end_date: date | None = Field(
        default=None, description="Employment end date as YYYY-MM-DD, when the CRM records one"
    )
    relationship_type_id: str | None = Field(
        default=None, description="Backstop id of the relationship type, when known."
    )
    relationship_type_name: str | None = Field(
        default=None,
        description=(
            "Name of the relationship type as this instance labels it, e.g. "
            "'is a former employee of'."
        ),
    )


class EmploymentLinkResponse(OmitNoneModel):
    """One resolved person↔organization employment pair for tool payloads.

    Always carries both sides. `status` is `current` or `former`; unknown pairs are omitted
    entirely rather than listed. `signal` / `end_date` are set only when `status` is `former`.
    Built via `EmploymentIndex.links()`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    status: EmploymentLinkStatus = Field(
        description=(
            "Whether this pair is current employment or a departure. Only 'current' and "
            "'former' appear here — pairs with no employment evidence are omitted."
        )
    )
    person_id: str = Field(description="Backstop id of the person this employment belongs to.")
    person_type: str = Field(
        description="Collection of that person: people, contacts, or employees."
    )
    organization_id: str = Field(
        description="Backstop id of the organization this employment links to."
    )
    organization_type: str = Field(
        description="Collection of that organization, typically 'organizations'."
    )
    signal: DepartureSignal | None = Field(
        default=None,
        description=(
            "Departure evidence when status is 'former': 'former_relationship_type' or "
            "'end_date_passed'. Absent for current employment."
        ),
    )
    end_date: date | None = Field(
        default=None, description="Employment end date as YYYY-MM-DD, when the CRM records one"
    )
    relationship_type_id: str | None = Field(
        default=None, description="Backstop id of the relationship type, when known."
    )
    relationship_type_name: str | None = Field(
        default=None,
        description=(
            "Name of the relationship type as this instance labels it, e.g. 'is employee of'."
        ),
    )


def as_of_response(as_of: AsOfResponse | None) -> AsOfResponse | None:
    return as_of


def departed_response(
    departure: DepartedEmploymentDto | None,
) -> DepartedContactResponse | None:
    if departure is None:
        return None
    return DepartedContactResponse.model_validate(departure)
