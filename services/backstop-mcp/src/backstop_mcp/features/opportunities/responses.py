"""The curated shape of one deal and one of its stage moves.

These are what a pipeline answer is made of, so every model carries a docstring and every field
a description: they are published as the tool's output schema, and a number with no unit or a
stage name with no direction is where a reader guesses wrong.

Both models are validated straight from a record's raw `attributes` — the camelCase aliases and
`extra="ignore"` below are what make that possible, and are the reason there is no separate wire
model to copy field for field. The few things Backstop does not put in `attributes` (the resource
id, the resolved stage name and id, the stage history) are supplied alongside by
`fetch.to_opportunity_response`. Validating one record at a time is deliberate: it is what keeps
a single malformed deal from costing a party their whole pipeline.

Backstop's names arrive as `validation_alias`, not `alias`, so they are read on the way in without
being published on the way out: the schema and `model_dump` keep the snake_case field names these
descriptions are written against. `populate_by_name` is what still allows either spelling in.

Two of Backstop's own shapes are deliberately not reproduced. `previousStage` is a plain string
naming the stage a deal has *left*, so it is described as such rather than left to read as the
current one. And a stage this instance can no longer name keeps its id with a null name, in both
`OpportunityResponse.stage` and `StageChangeResponse.stage`, because a move that happened is
still a fact even when the vocabulary has moved on.
"""

from typing import Annotated, ClassVar

from pydantic import BeforeValidator, ConfigDict, Field, StringConstraints

from backstop_mcp.dates import LenientDate
from backstop_mcp.models import OmitNoneModel

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


def _custom_field_values(value: object) -> object:
    """Read Backstop's explicit `regularCustomFieldValues: null` as "no custom fields".

    Measured on the live instance and not the same statement as an absent key: the attribute is
    present and null on records that simply have none, which is not a defect worth dropping the
    deal over.
    """
    return () if value is None else value


class StageChangeResponse(OmitNoneModel):
    """One move in a deal's stage history: which stage it entered, and when.

    Validated from a side-loaded `opportunity-stage-history` entry's `attributes`. That entry
    points at its stage through Backstop's inline `ResourceRef` format, which is resolved to
    `stage`/`stage_id` before validation rather than modelled here.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, extra="ignore", populate_by_name=True
    )

    stage: str | None = Field(
        default=None,
        description=(
            "Name of the stage the deal entered at this point. Null when this instance no "
            + "longer publishes that stage — read `stage_id`, and do not infer the name from "
            + "the surrounding entries."
        ),
    )
    stage_id: str | None = Field(
        default=None,
        description="Backstop id of that stage, kept even when the name could not be resolved.",
    )
    effective_date: LenientDate = Field(
        default=None,
        validation_alias="effectiveDate",
        description="Day the deal entered that stage.",
    )


class OpportunityResponse(OmitNoneModel):
    """One deal in the pipeline for a person or organization.

    Amounts are in `currency`; `probability` is a fraction, not a percentage. The stage timings
    (`days_open`, `days_in_current_stage`) are Backstop's own counters, carried through as they
    are stored.

    Every wire field is optional: a record missing one is still a deal worth reporting, and no
    field below was measured as load-bearing enough to drop the record over.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, extra="ignore", populate_by_name=True
    )

    id: str = Field(description="Backstop id of the opportunity.")
    name: _StrippedStr | None = Field(
        default=None,
        description="Name of the deal, usually 'investor - fund' — e.g. 'Koch - CATS Select'.",
    )
    stage: str | None = Field(
        default=None,
        description=(
            "The stage the deal is in now. Null when this instance no longer publishes that "
            + "stage; read `stage_id` in that case."
        ),
    )
    stage_id: str | None = Field(
        default=None,
        description="Backstop id of the current stage, kept even when the name is unresolved.",
    )
    previous_stage: _StrippedStr | None = Field(
        default=None,
        validation_alias="previousStage",
        description=(
            "The stage the deal most recently LEFT — not where it is now, which is `stage`. "
            + "Null until the deal has moved at all, since Backstop only records this once a "
            + "move has happened."
        ),
    )
    is_open: bool | None = Field(
        default=None,
        validation_alias="isOpen",
        description="Whether the deal is still open. False means it closed, won or lost.",
    )
    probability: float | None = Field(
        default=None,
        description="Backstop's likelihood of the deal closing, as a fraction: 0.3 is 30%.",
    )
    requested_amount: float | None = Field(
        default=None,
        validation_alias="requestedAmount",
        description="Amount the investor asked to commit, in `currency`.",
    )
    allocated_amount: float | None = Field(
        default=None,
        validation_alias="allocatedAmount",
        description="Amount allocated to the investor so far, in `currency`.",
    )
    currency: _StrippedStr | None = Field(
        default=None,
        validation_alias="currencyCode",
        description="ISO currency code both amounts are denominated in, e.g. 'USD'.",
    )
    expected_investment_date: LenientDate = Field(
        default=None,
        validation_alias="expectedInvestmentDate",
        description="Day the investment is expected to be made.",
    )
    closed_date: LenientDate = Field(
        default=None,
        validation_alias="closedDate",
        description="Day the deal closed; null while it is still open.",
    )
    days_open: int | None = Field(
        default=None,
        validation_alias="daysOpen",
        description="Backstop's count of days the deal has been open.",
    )
    days_in_current_stage: int | None = Field(
        default=None,
        validation_alias="daysInCurrentStage",
        description="Backstop's count of days the deal has sat in `stage`.",
    )
    date_entered_current_stage: LenientDate = Field(
        default=None,
        validation_alias="dateEnteredCurrentStage",
        description="Day the deal entered `stage`. Deals are returned newest-first by this day.",
    )
    custom_field_values: Annotated[
        tuple[dict[str, object], ...], BeforeValidator(_custom_field_values)
    ] = Field(
        default=(),
        validation_alias="regularCustomFieldValues",
        description=(
            "This instance's own custom fields on the deal, as Backstop stores them — one entry "
            + "per populated field, carrying its `definitionId`, `name` and `value`. Call "
            + "`list_custom_fields` for what a definition means."
        ),
    )
    stage_history: tuple[StageChangeResponse, ...] = Field(
        default=(),
        description=(
            "Every stage this deal has entered, in the order Backstop links them — the trail "
            + "behind `stage`."
        ),
    )
