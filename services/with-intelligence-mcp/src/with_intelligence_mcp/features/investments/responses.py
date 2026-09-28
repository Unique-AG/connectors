from typing import Self

from pydantic import Field

from with_intelligence_mcp.features.investments.api_responses import (
    InvestmentExtendedAttributes,
)
from with_intelligence_mcp.features.investors.api_responses import ClassificationAttributes
from with_intelligence_mcp.models import OmitNoneModel


class PositionAmountResponse(OmitNoneModel):
    value_millions: float | None = Field(
        default=None, description="Committed or held amount, in MILLIONS of `currency`."
    )
    as_of: str | None = Field(
        default=None, description="Date when With Intelligence measured this amount."
    )
    currency: str | None = Field(
        default=None, description="ISO-style currency code for `value_millions`."
    )


class PositionResponse(OmitNoneModel):
    """One position: a fund this investor holds, or held."""

    id: int = Field(description="With Intelligence position identifier.")
    fund: str | None = Field(default=None, description="Fund receiving the allocation.")
    fund_id: int | None = Field(
        default=None, description="With Intelligence identifier of the fund."
    )
    manager: str | None = Field(default=None, description="Firm managing the fund.")
    manager_id: int | None = Field(
        default=None, description="Use with manager_id filters to find their other investors."
    )
    amount: PositionAmountResponse | None = Field(
        default=None, description="Latest known committed or held amount."
    )
    asset_classes: list[str] | None = Field(
        default=None, description="Asset classes assigned to the position."
    )
    strategies: list[str] | None = Field(
        default=None, description="Primary and secondary investment strategies."
    )
    structures: list[str] | None = Field(
        default=None, description="Fund structures used by the position."
    )
    as_of: str | None = Field(default=None, description="When With Intelligence last confirmed it.")
    is_current: bool | None = Field(
        default=None, description="False once the position carries an exit date."
    )
    exited_on: str | None = Field(
        default=None, description="Exit date when this is no longer a current position."
    )
    fund_unidentified: bool | None = Field(
        default=None,
        description=(
            "With Intelligence records the position but could not identify which fund it is in."
        ),
    )

    @classmethod
    def from_attributes(cls, attributes: InvestmentExtendedAttributes) -> Self:
        detail_available = bool(attributes.model_fields_set - {"id"})
        strategy_available = bool(
            {"fund_primary_strategies", "fund_secondary_strategies"} & attributes.model_fields_set
        )
        return cls(
            id=attributes.id,
            fund=attributes.fund.name if attributes.fund else None,
            fund_id=attributes.fund.id if attributes.fund else None,
            manager=attributes.manager_firm.name if attributes.manager_firm else None,
            manager_id=attributes.manager_firm.id if attributes.manager_firm else None,
            amount=_amount(attributes),
            asset_classes=(
                _names(attributes.asset_classes)
                if "asset_classes" in attributes.model_fields_set
                else None
            ),
            strategies=(
                _names(attributes.fund_primary_strategies)
                + _names(attributes.fund_secondary_strategies)
                if strategy_available
                else None
            ),
            structures=(
                _names(attributes.fund_structures)
                if "fund_structures" in attributes.model_fields_set
                else None
            ),
            as_of=attributes.latest_as_of,
            is_current=not attributes.deleted_at if detail_available else None,
            exited_on=attributes.deleted_at,
            fund_unidentified=attributes.fund.unknown if attributes.fund else None,
        )


class InvestorPositionsResponse(OmitNoneModel):
    """An investor's fund roster — who they allocate to, and at what size."""

    investor_id: int = Field(description="With Intelligence investor identifier.")
    investor_name: str | None = Field(default=None, description="Resolved investor name.")
    positions: list[PositionResponse] = Field(
        default_factory=list, description="Positions on the requested page, newest first."
    )
    total: int = Field(
        default=0, description="How many positions With Intelligence holds in total."
    )
    returned: int = Field(default=0, description="Number of positions returned on this page.")
    page: int = Field(default=1, description="Page number represented by this response.")
    has_more: bool = Field(
        default=False, description="True when another page of positions is available."
    )


def _names(values: list[ClassificationAttributes]) -> list[str]:
    return [value.name for value in values if value.name]


def _amount(attributes: InvestmentExtendedAttributes) -> PositionAmountResponse | None:
    amount = attributes.amount
    if amount is None or amount.amount is None:
        return None
    return PositionAmountResponse(
        value_millions=amount.amount,
        as_of=amount.date,
        currency=amount.currency.short_name if amount.currency else None,
    )
