"""Wire shape for one `opportunities` record's `attributes`, as the page schema.

The field list is the instance's own `/resource-metadata/` entry for Opportunities, not the
swagger and not what one sampled record happened to carry: `aliases`, `associationType`,
`landingPageUrl`, `otherId` and `stageEffectiveDate` are declared there and simply arrive absent
on records that have no value for them. Everything the metadata calls a `resource:` or
`resource:List<>` field — `investor`, `product`, `stage`, `stageHistory`, `representative`, the
rest — is JSON:API linkage, not an attribute, and stays on `BackstopApiResource.relationships`.

**Every field is optional and every scalar is lenient, and that is what makes a typed page schema
safe here.** `client.paginate` deserializes a whole page in one pass, so a required field or a
strict type would fail all 100 opportunities over one malformed record — the reason the fetch
passed `dict[str, object]` in the first place. The `Lenient*` coercers turn an unparseable scalar
into `None` instead of a `ValidationError`, so the only remaining way to lose a page is a
structurally broken resource object (missing `id`, non-object `attributes`), which the untyped
dict would have failed on too.

Backstop's `type` attribute is the deal's *classification* (`"NTE"`, blank on most records), not
the JSON:API resource type sitting one level up. It is named `classification` here for the same
reason `previousStage` is spelled out in `responses.py`: the obvious reading is the wrong one.

Dates split by what actually arrives. `createdTimestamp` / `modifiedTimestamp` come as full
offset timestamps (`2020-06-24T17:10:52.842-0400`); the others come as midnight-local timestamps
that only mean a calendar day, and are read as one.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.dates import LenientDate, LenientDatetime
from backstop_mcp.features.custom_fields import RegularCustomFieldValues
from backstop_mcp.lenient import LenientBool, LenientFloat, LenientInt

__all__ = ["OpportunityResourceAttributes", "OpportunityResource"]


def _parse_lenient_str(value: object) -> str | None:
    """A stripped string, or None for a blank one and for anything that is not a string.

    Deliberately does not stringify numbers or bools: these are display fields, and a `name` that
    arrived as `42` is a defect worth reporting as absent rather than as the text "42".
    """
    if not isinstance(value, str):
        return None
    return value.strip() or None


LenientStr = Annotated[str | None, BeforeValidator(_parse_lenient_str)]


class OpportunityResourceAttributes(BaseModel):
    """Every attribute Backstop publishes on an `opportunities` record."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: LenientStr = None
    description: LenientStr = None
    aliases: LenientStr = None
    other_id: LenientStr = Field(default=None, alias="otherId")
    classification: LenientStr = Field(
        default=None,
        alias="type",
        description=(
            "Backstop's `type` attribute: the deal's classification, not its resource type."
        ),
    )
    association_type: LenientStr = Field(default=None, alias="associationType")
    landing_page_url: LenientStr = Field(default=None, alias="landingPageUrl")

    is_open: LenientBool = Field(default=None, alias="isOpen")
    is_erisa: LenientBool = Field(default=None, alias="isErisa")
    previous_stage: LenientStr = Field(default=None, alias="previousStage")

    probability: LenientFloat = None
    requested_amount: LenientFloat = Field(default=None, alias="requestedAmount")
    allocated_amount: LenientFloat = Field(default=None, alias="allocatedAmount")
    weighted_value: LenientFloat = Field(default=None, alias="weightedValue")
    weighted_allocated_value: LenientFloat = Field(default=None, alias="weightedAllocatedValue")
    currency_code: LenientStr = Field(default=None, alias="currencyCode")

    days_open: LenientInt = Field(default=None, alias="daysOpen")
    days_in_current_stage: LenientInt = Field(default=None, alias="daysInCurrentStage")
    waitlist_id: LenientInt = Field(default=None, alias="waitlistId")

    effective_date: LenientDate = Field(default=None, alias="effectiveDate")
    closed_date: LenientDate = Field(default=None, alias="closedDate")
    expected_investment_date: LenientDate = Field(default=None, alias="expectedInvestmentDate")
    date_entered_current_stage: LenientDate = Field(default=None, alias="dateEnteredCurrentStage")
    stage_effective_date: LenientDate = Field(default=None, alias="stageEffectiveDate")

    created_timestamp: LenientDatetime = Field(default=None, alias="createdTimestamp")
    modified_timestamp: LenientDatetime = Field(default=None, alias="modifiedTimestamp")

    regular_custom_field_values: RegularCustomFieldValues = Field(
        default_factory=list, alias="regularCustomFieldValues"
    )


OpportunityResource = BackstopApiResource[OpportunityResourceAttributes]
