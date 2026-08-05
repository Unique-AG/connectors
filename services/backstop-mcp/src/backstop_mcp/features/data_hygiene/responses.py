"""Tool-facing echoes for provenance and departed-contact signals."""

from pydantic import BaseModel, Field

from backstop_mcp.features.data_hygiene.types import AsOf, DepartedEmployment, DepartureSignal


class AsOfEcho(BaseModel):
    """Plain provenance. Relay to the user; do not treat age as a staleness verdict."""

    modified_timestamp: str | None = Field(default=None, description="Backstop modifiedTimestamp")
    modified_by: str | None = Field(default=None, description="Backstop modifiedBy")


class DepartedContactEcho(BaseModel):
    """Hard signal that employment at an organization has ended. Always relay this flag."""

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
    end_date: str | None = Field(
        default=None, description="Employment end date as YYYY-MM-DD, when the CRM records one"
    )
    relationship_type_id: str | None = None
    relationship_type_name: str | None = None


def as_of_echo(value: AsOf | None) -> AsOfEcho | None:
    if value is None:
        return None
    return AsOfEcho(
        modified_timestamp=value.modified_timestamp,
        modified_by=value.modified_by,
    )


def departed_echo(value: DepartedEmployment | None) -> DepartedContactEcho | None:
    if value is None:
        return None
    return DepartedContactEcho(
        signal=value.signal,
        organization_id=value.organization_id,
        organization_type=value.organization_type,
        end_date=value.end_date,
        relationship_type_id=value.relationship_type_id,
        relationship_type_name=value.relationship_type_name,
    )
