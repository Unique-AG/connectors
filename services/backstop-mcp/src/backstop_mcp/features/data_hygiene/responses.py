"""Tool-facing responses for provenance and departed-contact signals."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.data_hygiene.types import AsOf, DepartedEmployment, DepartureSignal


class DepartedContactResponse(BaseModel):
    """Hard signal that employment at an organization has ended. Always relay this flag."""

    model_config = ConfigDict(from_attributes=True)

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


def as_of_response(as_of: AsOf | None) -> AsOf | None:
    return as_of


def departed_response(departure: DepartedEmployment | None) -> DepartedContactResponse | None:
    if departure is None:
        return None
    return DepartedContactResponse.model_validate(departure)
