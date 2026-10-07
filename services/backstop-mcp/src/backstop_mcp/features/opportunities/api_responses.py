"""Wire shapes for opportunity records, the stage vocabulary, and search includes.

The field list on `OpportunityResourceAttributes` is the instance's own `/resource-metadata/`
entry for Opportunities, not the swagger and not what one sampled record happened to carry:
`aliases`, `associationType`, `landingPageUrl`, `otherId` and `stageEffectiveDate` are declared
there and simply arrive absent on records that have no value for them. Everything the metadata
calls a `resource:` or `resource:List<>` field — `investor`, `product`, `stage`, `stageHistory`,
`representative`, the rest — is JSON:API linkage, not an attribute, and stays on
`BackstopApiResource.relationships`.

**Every field is optional and every scalar is lenient, and that is what makes a typed page schema
safe here.** `client.paginate` deserializes a whole page in one pass, so a required field or a
strict type would fail a whole page over one malformed record. The `Lenient*` coercers turn an
unparseable scalar into `None` instead of a `ValidationError`, so the only remaining way to lose
a page is a structurally broken resource object (missing `id`, non-object `attributes`).

Backstop's `type` attribute is the deal's classification (a short code, blank on most records),
not the JSON:API resource type sitting one level up. It is named `classification` here for the
same reason `previousStage` is spelled out in `responses.py`: the obvious reading is the wrong one.

Dates split by what actually arrives. `createdTimestamp` / `modifiedTimestamp` come as full
offset timestamps; the others come as midnight-local timestamps that only mean a calendar day,
and are read as one.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResource, ResourceRef
from backstop_mcp.dates import LenientDate, LenientDatetime
from backstop_mcp.features.custom_fields import RegularCustomFieldValues
from backstop_mcp.lenient import LenientBool, LenientFloat, LenientInt, LenientStr
from backstop_mcp.models import StrippedStr

__all__ = [
    "OpportunityResource",
    "OpportunityResourceAttributes",
    "OpportunityStageAttributes",
    "OpportunityStageHistoryAttributes",
    "SearchContactAttributes",
    "SearchProductAttributes",
    "SearchProductConfigurationAttributes",
]


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
    client_defined_entity_type: LenientInt = Field(default=None, alias="clientDefinedEntityType")


OpportunityResource = BackstopApiResource[OpportunityResourceAttributes]


class OpportunityStageAttributes(BaseModel):
    """Wire shape for `opportunity-stages` attributes (the vocabulary subset).

    Every field is optional because `client.paginate` deserializes a whole page in one pass: a
    required field would fail the fetch over one malformed row. Optional fields plus the drop
    in `OpportunityStageResponse.from_resource` keep one bad row from costing the rest.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: StrippedStr | None = None
    sort_order: LenientInt = Field(default=None, alias="sortOrder")
    closed: LenientBool = None
    probability: LenientFloat = None


class SearchContactAttributes(BaseModel):
    """Sparse `contacts` attributes from the investor include on `GET /opportunities`.

    `specificResource` names the concrete collection (`organizations` / `people`) under the
    same id; `fields[contacts]` accepts it.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    specific_resource: ResourceRef | None = Field(default=None, alias="specificResource")


class SearchProductConfigurationAttributes(BaseModel):
    """`attributes.configuration` on the product include; the short name lives only here.

    `fields[products]=productShortName` is `400`, so there is no top-level short name to read.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    product_short_name: str | None = Field(default=None, validation_alias="productShortName")


class SearchProductAttributes(BaseModel):
    """Sparse `products` attributes (`name,configuration`) from the opportunity product include."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: str | None = None
    configuration: SearchProductConfigurationAttributes | None = None


class OpportunityStageHistoryAttributes(BaseModel):
    """Wire attributes on a side-loaded `opportunity-stage-history` entry.

    `stage` is Backstop's inline `{resourceType, resourceId}` object; it is resolved to a name
    after this model is read, not here.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    stage: object | None = None
    effective_date: LenientDate = Field(default=None, alias="effectiveDate")
