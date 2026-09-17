"""PATCH fields for `update_opportunity`.

`opportunity_id` is required. Every other field is optional — omit to leave it unchanged.
At least one change field must be set.

Excluded (derived or read-only; Backstop computes them): `weightedValue`,
`weightedAllocatedValue`, `isOpen`, `previousStage`, `daysOpen`, `daysInCurrentStage`,
`dateEnteredCurrentStage`, `closedDate`, `effectiveDate`, `landingPageUrl`,
`associationType`. `regularCustomFieldValues` goes through `update_custom_field_values`,
which validates against the catalog. `permissionBucket` is out of scope.
"""

from datetime import date
from typing import Self

from pydantic import BaseModel, Field, model_validator

from backstop_mcp.features.opportunity_writes._opportunity_writable_fields import (
    CURRENCY_CODE_DESCRIPTION,
    IS_ERISA_DESCRIPTION,
    NAME_DESCRIPTION,
    _OpportunityWritableFields,
)
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "UPDATE_OPPORTUNITY_INPUT_DESCRIPTION",
    "UpdateOpportunityInput",
]

UPDATE_OPPORTUNITY_INPUT_DESCRIPTION = (
    "Required. The opportunity to patch. Needs `opportunity_id` and at least one field to "
    "change. `stage` is a stage name from this instance's vocabulary, not an id. "
    "`probability` is a fraction (0.3 is 30%) and is not changed by setting a stage. "
    "Omit a field to leave it unchanged. Never invent an id."
)

_IDENTITY_FIELDS = frozenset({"opportunity_id"})


class _UpdateOpportunityIdentity(BaseModel):
    """Opportunity id. Inherited first so it leads the published schema."""

    opportunity_id: NonEmptyStr = Field(
        description=(
            "Required. Backstop opportunity id from `get_opportunities` or "
            "`get_opportunities_by_ids`. Never invent or guess."
        )
    )


class UpdateOpportunityInput(_UpdateOpportunityIdentity, _OpportunityWritableFields):
    """PATCH an opportunity. Only supplied fields are sent; PATCH is merge."""

    name: NonEmptyStr | None = Field(default=None, description=NAME_DESCRIPTION)
    currency_code: NonEmptyStr | None = Field(default=None, description=CURRENCY_CODE_DESCRIPTION)
    is_erisa: bool | None = Field(default=None, description=IS_ERISA_DESCRIPTION)
    investor_id: NonEmptyStr | None = Field(
        default=None,
        description="Replacement investor contact id (`contacts`). Never invent or guess.",
    )
    add_users_to_notify: tuple[str, ...] | None = Field(
        default=None,
        min_length=1,
        description=(
            "System-user logins to append to the notify list (Backstop CC). One PATCH; "
            "Backstop appends to-many relationships. At least one login. Unknown logins "
            "are skipped and listed in `warnings`. Cannot be combined with "
            "`replace_users_to_notify`. To clear the list, use "
            "`replace_users_to_notify=[]`."
        ),
    )
    replace_users_to_notify: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Set the notify list (Backstop CC) to exactly these `list_system_users` logins. "
            "Two PATCHes (clear, then add) because a to-many PATCH appends and `data: []` "
            "is the only clear. If the second PATCH fails, the list is left empty. An empty "
            "tuple clears the list. Unknown logins are skipped and listed in `warnings`; "
            "if none resolve, the list is left unchanged. Cannot be combined with "
            "`add_users_to_notify`. There is no way to remove a single member."
        ),
    )
    stage_effective_date: date | None = Field(
        default=None,
        description=(
            "Day the stage move should be dated. Requires `stage`. A date earlier than the "
            "deal's `dateEnteredCurrentStage` is rejected: Backstop would write history "
            "without moving the deal. Omit to move the deal today."
        ),
    )

    @model_validator(mode="after")
    def _at_least_one_change(self) -> Self:
        for name in type(self).model_fields:
            if name in _IDENTITY_FIELDS:
                continue
            if getattr(self, name) is not None:
                return self
        raise ValueError("Pass at least one field to change")

    @model_validator(mode="after")
    def _stage_effective_date_requires_stage(self) -> Self:
        if self.stage_effective_date is not None and self.stage is None:
            raise ValueError("stage_effective_date requires stage")
        return self

    @model_validator(mode="after")
    def _notify_fields_are_exclusive(self) -> Self:
        if self.add_users_to_notify is not None and self.replace_users_to_notify is not None:
            raise ValueError("Set add_users_to_notify or replace_users_to_notify, not both")
        return self
