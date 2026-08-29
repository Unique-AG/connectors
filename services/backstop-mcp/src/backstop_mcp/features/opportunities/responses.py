"""The curated shape of one deal and one of its stage moves.

These are what a pipeline answer is made of, so every model carries a docstring and every field
a description: they are published as the tool's output schema, and a number with no unit or a
stage name with no direction is where a reader guesses wrong.

Both models are validated straight from a record's raw `attributes` — the camelCase aliases and
`extra="ignore"` below are what make that possible, and are the reason there is no separate wire
model to copy field for field. The few things Backstop does not put in `attributes` (the resource
id, the resolved stage name and id, the stage history, and custom-field values) are supplied
alongside by `OpportunityResponse.from_resource`. Validating one record at a time is deliberate:
it is what keeps a single malformed deal from costing a party their whole pipeline.

Backstop's names arrive as `validation_alias`, not `alias`, so they are read on the way in without
being published on the way out: the schema and `model_dump` keep the snake_case field names these
descriptions are written against. `populate_by_name` is what still allows either spelling in.

Two of Backstop's own shapes are deliberately not reproduced. `previousStage` is a plain string
naming the stage a deal has *left*, so it is described as such rather than left to read as the
current one. And a stage this instance can no longer name keeps its id with the name omitted, in
both `OpportunityResponse.stage` and `StageChangeResponse.stage`, because a move that happened is
still a fact even when the vocabulary has moved on.
"""

from typing import Annotated, ClassVar, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.dates import LenientDate
from backstop_mcp.features.custom_fields import ResolvedCustomFieldValueResponse
from backstop_mcp.features.opportunities.queries.opportuntity_resource import (
    OpportunityResourceAttributes,
)
from backstop_mcp.models import OmitNoneModel

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


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
            "Name of the stage the deal entered at this point. Omitted when this instance no "
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
            "The stage the deal is in now. Omitted when this instance no longer publishes that "
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
            + "Omitted until the deal has moved at all, since Backstop only records this once a "
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
        description=(
            "Backstop's standard likelihood of the deal closing, as a fraction: 0.3 is 30%. "
            "A rep-entered probability custom field stays in `custom_field_values` under its "
            "own name — do not treat that as this field."
        ),
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
    weighted_value: float | None = Field(
        default=None,
        validation_alias="weightedValue",
        description=(
            "Backstop's requested amount times `probability`. Use this for book-wide "
            "prioritization, not a hand-computed product of the two."
        ),
    )
    weighted_allocated_value: float | None = Field(
        default=None,
        validation_alias="weightedAllocatedValue",
        description="Backstop's allocated amount times `probability`.",
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
        description="Day the deal closed; omitted while it is still open.",
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
    custom_field_values: tuple[ResolvedCustomFieldValueResponse, ...] = Field(
        default=(),
        description=(
            "Custom-field values on the deal, joined to list_custom_fields definitions "
            "(definition id, name, type, and value). Empty when the deal has none or the "
            "catalog could not be loaded. Slice with custom_field_names / "
            "custom_field_definition_ids rather than fetching again."
        ),
    )
    stage_history: tuple[StageChangeResponse, ...] = Field(
        default=(),
        description=(
            "Every stage this deal has entered, in the order Backstop links them — the trail "
            + "behind `stage`. Empty on get_opportunities_by_ids unless include_stage_history "
            + "was requested — that is omission, not 'never moved'."
        ),
    )

    @classmethod
    def from_resource(
        cls,
        resource: BackstopApiResource[OpportunityResourceAttributes | dict[str, object]],
        *,
        stage: str | None,
        stage_id: str | None,
        stage_history: tuple[StageChangeResponse, ...],
        custom_field_values: tuple[ResolvedCustomFieldValueResponse, ...],
    ) -> Self:
        """Project one `opportunities` resource, naming its current stage and its history.

        The response model reads the record's attributes through its own aliases, so the things
        Backstop does not put in `attributes` are all that is supplied here. Raises
        `ValidationError` for a record the model cannot read, which the caller drops on its own.
        """
        attributes = resource.attributes
        dumped = (
            attributes if isinstance(attributes, dict) else attributes.model_dump(by_alias=True)
        )
        return cls.model_validate(
            {
                **dumped,
                "id": resource.id,
                "stage": stage,
                "stage_id": stage_id,
                "stage_history": stage_history,
                "custom_field_values": custom_field_values,
            }
        )


class GetOpportunitiesResponse(OmitNoneModel):
    """One party's opportunities after filtering and ordering, plus what the whole set says.

    `total` and the two counts are over everything fetched — the party's complete set, since the
    fetch walks their whole sub-collection — so `status="open"` still reports how many closed
    deals exist.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    opportunities: tuple[OpportunityResponse, ...] = Field(
        description=(
            "The deals matching the requested status, newest first by the day each entered its "
            + "current stage."
        )
    )
    total: int = Field(
        description=(
            "Every opportunity fetched for this party, before filtering by status — so the "
            + "number they have in total. Counted here rather than read from Backstop's own "
            + "`meta.totalResourceCount`."
        )
    )
    open_count: int = Field(
        description=(
            "How many of those are open, whatever status was asked for — so an answer about "
            + "open deals still says how many exist."
        )
    )
    closed_count: int = Field(
        description="How many of those are closed, counted the same way as `open_count`."
    )


class OpportunityIdErrorResponse(OmitNoneModel):
    """One id in a by-ids batch that failed for a reason other than 404."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="The opportunity id that failed.")
    detail: str = Field(description="Why this id was not returned.")


class GetOpportunitiesByIdsResponse(OmitNoneModel):
    """A completed by-id batch: found deals, missing ids, and per-id errors."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': every requested id was attempted.",
    )
    opportunities: tuple[OpportunityResponse, ...] = Field(
        description="Deals that were found, in the order their ids were requested."
    )
    not_found: tuple[str, ...] = Field(
        default=(),
        description="Requested ids that Backstop answered as 404.",
    )
    errors: tuple[OpportunityIdErrorResponse, ...] = Field(
        default=(),
        description="Requested ids that failed for a reason other than 404.",
    )
