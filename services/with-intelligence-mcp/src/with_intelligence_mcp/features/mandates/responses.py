from typing import Self

from pydantic import Field

from with_intelligence_mcp.features.investors.api_responses import ClassificationAttributes
from with_intelligence_mcp.features.mandates.api_responses import (
    MandateExtendedAttributes,
    MandateNoteAttributes,
)
from with_intelligence_mcp.models import OmitNoneModel


class MandateAmountResponse(OmitNoneModel):
    value_millions: float | None = Field(
        default=None, description="Size of the search, in MILLIONS of `currency`."
    )
    currency: str | None = None


class MandateResponse(OmitNoneModel):
    """One allocation search by this investor."""

    id: int
    status: str | None = Field(
        default=None, description="Where the search stands, in With Intelligence's own words."
    )
    sub_status: str | None = None
    service: str | None = Field(
        default=None, description="What kind of mandate it is, e.g. a manager search."
    )
    amount: MandateAmountResponse | None = None
    asset_classes: list[str] | None = None
    strategies: list[str] | None = None
    structures: list[str] | None = None
    market_focuses: list[str] | None = None
    awarded_to: str | None = Field(default=None, description="The fund that won it, once one has.")
    consultant: str | None = None
    consultant_firm: str | None = None
    rfp_link: str | None = None
    last_reviewed: str | None = Field(
        default=None,
        description="When With Intelligence last confirmed it. An old date is a stale mandate.",
    )
    updated_at: str | None = None
    note: str | None = None
    latest_note: str | None = None
    latest_note_date: str | None = None

    @classmethod
    def from_attributes(cls, attributes: MandateExtendedAttributes) -> Self:
        latest_note = _latest_note(attributes)
        strategies_available = bool(
            {"primary_strategies", "secondary_strategies"} & attributes.model_fields_set
        )
        return cls(
            id=attributes.id,
            status=attributes.status.name if attributes.status else None,
            sub_status=(
                attributes.status.sub_status.name
                if attributes.status and attributes.status.sub_status
                else None
            ),
            service=attributes.service.name if attributes.service else None,
            amount=_amount(attributes),
            asset_classes=(
                _names(attributes.asset_class)
                if "asset_class" in attributes.model_fields_set
                else None
            ),
            strategies=(
                _names(attributes.primary_strategies) + _names(attributes.secondary_strategies)
                if strategies_available
                else None
            ),
            structures=(
                _names(attributes.fund_structures)
                if "fund_structures" in attributes.model_fields_set
                else None
            ),
            market_focuses=(
                _names(attributes.market_focuses)
                if "market_focuses" in attributes.model_fields_set
                else None
            ),
            awarded_to=attributes.fund.name if attributes.fund else None,
            consultant=attributes.consultant,
            consultant_firm=(
                attributes.primary_consultant_firm.name
                if attributes.primary_consultant_firm
                else None
            ),
            rfp_link=attributes.rfp_link,
            last_reviewed=attributes.last_reviewed.date if attributes.last_reviewed else None,
            updated_at=attributes.updated_at,
            note=attributes.note,
            latest_note=latest_note.note if latest_note else None,
            latest_note_date=latest_note.date if latest_note else None,
        )


class InvestorMandatesResponse(OmitNoneModel):
    """An investor's allocation searches, newest first.

    Status is With Intelligence's vocabulary, not a boolean: read it rather than assuming "active".
    """

    investor_id: int
    investor_name: str | None = None
    mandates: list[MandateResponse] = Field(default_factory=list)
    total: int = Field(default=0, description="How many mandates With Intelligence holds in total.")
    returned: int = 0
    page: int = 1
    has_more: bool = False


def _names(values: list[ClassificationAttributes]) -> list[str]:
    return [value.name for value in values if value.name]


def _amount(attributes: MandateExtendedAttributes) -> MandateAmountResponse | None:
    amount = attributes.amount
    if amount is None or amount.amount is None:
        return None
    return MandateAmountResponse(
        value_millions=amount.amount,
        currency=amount.currency.short_name if amount.currency else None,
    )


def _latest_note(attributes: MandateExtendedAttributes) -> MandateNoteAttributes | None:
    dated = [entry for entry in attributes.notes if entry.date]
    if dated:
        return max(dated, key=lambda entry: entry.date or "")
    return attributes.notes[0] if attributes.notes else None
