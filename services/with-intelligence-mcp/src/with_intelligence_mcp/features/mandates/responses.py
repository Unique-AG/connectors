from typing import Self

from pydantic import Field

from with_intelligence_mcp.features.investors.api_responses import ClassificationAttributes
from with_intelligence_mcp.features.mandates.api_responses import (
    MandateExtendedAttributes,
    MandateNoteAttributes,
)
from with_intelligence_mcp.models import OmitNoneModel
from with_intelligence_mcp.utils import html_to_markdown


class MandateAmountResponse(OmitNoneModel):
    value_millions: float | None = Field(
        default=None,
        description="Target allocation size, in MILLIONS of `currency`.",
        examples=[300.0],
    )
    currency: str | None = Field(
        default=None,
        description="ISO-style currency code for `value_millions`.",
        examples=["USD"],
    )


class MandateResponse(OmitNoneModel):
    """One allocation search by this investor."""

    id: int = Field(description="With Intelligence mandate identifier.", examples=[21])
    status: str | None = Field(
        default=None,
        description="With Intelligence's current mandate status; do not infer a boolean.",
        examples=["Open"],
    )
    sub_status: str | None = Field(
        default=None,
        description="More specific stage within `status`.",
        examples=["Shortlisting"],
    )
    service: str | None = Field(
        default=None,
        description="Type of advisory or allocation search.",
        examples=["Manager Search"],
    )
    amount: MandateAmountResponse | None = Field(
        default=None, description="Known target allocation amount."
    )
    asset_classes: list[str] | None = Field(
        default=None,
        description="Asset classes targeted by the mandate.",
        examples=[["Hedge Funds"]],
    )
    strategies: list[str] | None = Field(
        default=None,
        description="Primary and secondary strategies targeted by the mandate.",
        examples=[["Equity", "Long/Short Equity"]],
    )
    structures: list[str] | None = Field(
        default=None,
        description="Acceptable fund or account structures.",
        examples=[["Managed Account"]],
    )
    market_focuses: list[str] | None = Field(
        default=None,
        description="Geographic or market areas targeted by the mandate.",
        examples=[["North America"]],
    )
    awarded_to: str | None = Field(
        default=None,
        description="Fund awarded the mandate after selection.",
        examples=["Example Global Macro Fund"],
    )
    consultant: str | None = Field(
        default=None, description="Consultant contact associated with the mandate."
    )
    consultant_firm: str | None = Field(
        default=None, description="Consulting firm running or advising on the mandate."
    )
    rfp_link: str | None = Field(
        default=None, description="Public request-for-proposal URL when available."
    )
    last_reviewed: str | None = Field(
        default=None,
        description="When With Intelligence last confirmed it. An old date is a stale mandate.",
        examples=["2026-06-30"],
    )
    updated_at: str | None = Field(
        default=None,
        description="When With Intelligence last changed this mandate record.",
        examples=["2026-08-01"],
    )
    note: str | None = Field(
        default=None, description="General note stored directly on the mandate."
    )
    latest_note: str | None = Field(
        default=None, description="Most recent dated note from the mandate's note history."
    )
    latest_note_date: str | None = Field(
        default=None,
        description="Date associated with `latest_note`.",
        examples=["2026-07-15"],
    )

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
            note=html_to_markdown(attributes.note),
            latest_note=html_to_markdown(latest_note.note) if latest_note else None,
            latest_note_date=latest_note.date if latest_note else None,
        )


class InvestorMandatesResponse(OmitNoneModel):
    """An investor's allocation searches, newest first.

    Status is With Intelligence's vocabulary, not a boolean: read it rather than assuming "active".
    """

    investor_id: int = Field(description="With Intelligence investor identifier.")
    investor_name: str | None = Field(default=None, description="Resolved investor name.")
    mandates: list[MandateResponse] = Field(
        default_factory=list, description="Mandates on the requested page, newest first."
    )
    total: int = Field(default=0, description="How many mandates With Intelligence holds in total.")
    returned: int = Field(default=0, description="Number of mandates returned on this page.")
    page: int = Field(default=1, description="Page number represented by this response.")
    has_more: bool = Field(
        default=False, description="True when another page of mandates is available."
    )


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
