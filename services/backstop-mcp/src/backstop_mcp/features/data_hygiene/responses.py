"""Tool-facing responses for provenance and employment links."""

from datetime import date
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.data_hygiene.types import AsOf, DepartedEmployment, DepartureSignal

type EmploymentLinkStatus = Literal["current", "former"]


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
    organization_id: str
    organization_type: str
    end_date: date | None = Field(
        default=None, description="Employment end date as YYYY-MM-DD, when the CRM records one"
    )
    relationship_type_id: str | None = None
    relationship_type_name: str | None = None


class EmploymentLinkResponse(BaseModel):
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
    person_id: str
    person_type: str
    organization_id: str
    organization_type: str
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
    relationship_type_id: str | None = None
    relationship_type_name: str | None = None


def as_of_response(as_of: AsOf | None) -> AsOf | None:
    return as_of


def departed_response(departure: DepartedEmployment | None) -> DepartedContactResponse | None:
    if departure is None:
        return None
    return DepartedContactResponse.model_validate(departure)
