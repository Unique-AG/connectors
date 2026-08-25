from datetime import date
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes

__all__ = [
    "InvestorChipDto",
    "OpportunityStageDto",
    "ProductChipDto",
    "SearchOpportunitiesFetchDto",
    "SearchOpportunityDto",
]


class OpportunityStageDto(BaseModel):
    """One row of the instance's opportunity-stage vocabulary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str
    closed: bool = False
    sort_order: int | None = None

    @classmethod
    def from_resource(
        cls, resource: BackstopApiResource[OpportunityStageAttributes]
    ) -> Self | None:
        """Map one `opportunity-stages` resource onto the vocabulary shape.

        Returns None when `name` is missing — naming a stage is the whole point of this
        vocabulary, so an unnamed row would only masquerade as a resolution.
        """
        name = resource.attributes.name
        if not name:
            return None
        return cls(
            id=resource.id,
            name=name,
            closed=bool(resource.attributes.closed),
            sort_order=resource.attributes.sort_order,
        )


class InvestorChipDto(BaseModel):
    """The investor side-load on a firm-wide opportunity (`contacts`, not organizations)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None


class ProductChipDto(BaseModel):
    """The product side-load on a firm-wide opportunity."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None


class SearchOpportunityDto(BaseModel):
    """One deal from `GET /opportunities`, plus investor and product chips when they arrived."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    stage: str | None = None
    stage_id: str | None = None
    previous_stage: str | None = None
    is_open: bool | None = None
    probability: float | None = None
    requested_amount: float | None = None
    allocated_amount: float | None = None
    weighted_value: float | None = None
    weighted_allocated_value: float | None = None
    currency: str | None = None
    expected_investment_date: date | None = None
    closed_date: date | None = None
    days_open: int | None = None
    days_in_current_stage: int | None = None
    date_entered_current_stage: date | None = None
    investor: InvestorChipDto | None = None
    product: ProductChipDto | None = None


class SearchOpportunitiesFetchDto(BaseModel):
    """Projected deals from one firm-wide walk, plus how much of the collection was seen.

    `truncated` is the walk's scan ceiling firing. There is deliberately no partial-scan flag:
    the walk is one `paginate` call and a failed page fails the whole thing, so a short answer
    is never returned in place of an error.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rows: tuple[SearchOpportunityDto, ...]
    rows_received: int
    rows_dropped: int
    total_count: int | None
    truncated: bool
