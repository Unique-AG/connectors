"""The curated shape of one deal and one of its stage moves.

These are what a pipeline answer is made of, so every model carries a docstring and every field
a description: they are published as the tool's output schema, and a number with no unit or a
stage name with no direction is where a reader guesses wrong.

Two of Backstop's own shapes are deliberately not reproduced. `previousStage` is a plain string
naming the stage a deal has *left*, so it is described as such rather than left to read as the
current one. And a stage this instance can no longer name keeps its id with a null name, in both
`OpportunityResponse.stage` and `StageChangeResponse.stage`, because a move that happened is
still a fact even when the vocabulary has moved on.
"""

from datetime import date
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class StageChangeResponse(BaseModel):
    """One move in a deal's stage history: which stage it entered, and when."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

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
    effective_date: date | None = Field(
        default=None, description="Day the deal entered that stage."
    )


class OpportunityResponse(BaseModel):
    """One deal in the pipeline for a person or organization.

    Amounts are in `currency`; `probability` is a fraction, not a percentage. The stage timings
    (`days_open`, `days_in_current_stage`) are Backstop's own counters, carried through as they
    are stored.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of the opportunity.")
    name: str | None = Field(
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
    previous_stage: str | None = Field(
        default=None,
        description=(
            "The stage the deal most recently LEFT — not where it is now, which is `stage`. "
            + "Null until the deal has moved at all, since Backstop only records this once a "
            + "move has happened."
        ),
    )
    is_open: bool | None = Field(
        default=None,
        description="Whether the deal is still open. False means it closed, won or lost.",
    )
    probability: float | None = Field(
        default=None,
        description="Backstop's likelihood of the deal closing, as a fraction: 0.3 is 30%.",
    )
    requested_amount: float | None = Field(
        default=None, description="Amount the investor asked to commit, in `currency`."
    )
    allocated_amount: float | None = Field(
        default=None, description="Amount allocated to the investor so far, in `currency`."
    )
    currency: str | None = Field(
        default=None, description="ISO currency code both amounts are denominated in, e.g. 'USD'."
    )
    expected_investment_date: date | None = Field(
        default=None, description="Day the investment is expected to be made."
    )
    closed_date: date | None = Field(
        default=None, description="Day the deal closed; null while it is still open."
    )
    days_open: int | None = Field(
        default=None, description="Backstop's count of days the deal has been open."
    )
    days_in_current_stage: int | None = Field(
        default=None, description="Backstop's count of days the deal has sat in `stage`."
    )
    date_entered_current_stage: date | None = Field(
        default=None,
        description="Day the deal entered `stage`. Deals are returned newest-first by this day.",
    )
    custom_field_values: tuple[dict[str, object], ...] = Field(
        default=(),
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
