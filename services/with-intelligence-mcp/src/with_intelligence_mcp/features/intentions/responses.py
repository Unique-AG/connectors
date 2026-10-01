from typing import Self

from pydantic import Field

from with_intelligence_mcp.features.intentions.api_responses import (
    IntentionAmountAttributes,
    IntentionExtendedAttributes,
    IntentionListItemAttributes,
    IntentionPreferenceAttributes,
)
from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.models import OmitNoneModel


class IntentionAmountResponse(OmitNoneModel):
    lower_usd: float | None = Field(
        default=None,
        description="Lower bound in US dollars, not millions.",
    )
    upper_usd: float | None = Field(
        default=None,
        description="Upper bound in US dollars, not millions.",
    )


class IntentionPreferenceResponse(OmitNoneModel):
    name: str | None = Field(default=None, description="What the preference is about.")
    sentiment: str | None = Field(
        default=None, description="With Intelligence's sentiment toward it, in their wording."
    )
    type: str | None = Field(default=None, description="Kind of preference.")


class IntentionResponse(OmitNoneModel):
    """One forward-looking allocation intention."""

    id: int = Field(description="With Intelligence intention identifier.", examples=[7])
    date: str | None = Field(
        default=None, description="Date of the intention.", examples=["2026-06-01"]
    )
    updated_at: str | None = Field(
        default=None, description="When With Intelligence last changed this intention."
    )
    status: str | None = Field(
        default=None,
        description="With Intelligence's status name. Do not infer a boolean.",
        examples=["Potential"],
    )
    sub_status: str | None = Field(
        default=None, description="More specific stage within `status`.", examples=["Early"]
    )
    asset_class: str | None = Field(
        default=None, description="Asset class this intention covers.", examples=["Hedge Funds"]
    )
    strategies: list[str] | None = Field(
        default=None,
        description="Primary strategy, then secondaries.",
        examples=[["Global Macro", "Discretionary"]],
    )
    structures: list[str] | None = Field(
        default=None, description="Acceptable structures.", examples=[["Commingled"]]
    )
    themes: list[str] | None = Field(default=None, description="Themes attached to the intention.")
    allocation_amount: IntentionAmountResponse | None = Field(
        default=None, description="Planned allocation, in US dollars."
    )
    ticket_size: IntentionAmountResponse | None = Field(
        default=None, description="Ticket size band, in US dollars."
    )
    note: str | None = Field(default=None, description="Note stored on the intention.")
    preference_only: bool | None = Field(
        default=None,
        description="True when this row is a stated preference rather than a live search.",
    )
    search_consultant: bool | None = Field(
        default=None, description="Whether the investor is searching for a consultant."
    )
    preferences: list[IntentionPreferenceResponse] | None = Field(
        default=None,
        description="Stated preferences on this intention, when the add-on sends them.",
    )

    @classmethod
    def from_attributes(cls, attributes: IntentionExtendedAttributes) -> Self:
        status = attributes.status
        segments = attributes.classification_segments
        strategies = segments.strategies if segments else None
        return cls(
            id=attributes.id,
            date=attributes.date,
            updated_at=attributes.updated_at,
            status=status.name if status else None,
            sub_status=status.sub_status.name if status and status.sub_status else None,
            asset_class=attributes.asset_class.name if attributes.asset_class else None,
            strategies=_strategy_names(strategies.primary_strategy, strategies.secondary_strategies)
            if strategies
            else None,
            structures=_when_present(attributes, "structures", _names(attributes.structures)),
            themes=_when_present(attributes, "themes", _names(attributes.themes)),
            allocation_amount=_amount(attributes.allocation_amount),
            ticket_size=_amount(attributes.ticket_size),
            note=attributes.note,
            preference_only=attributes.preference_only,
            search_consultant=attributes.search_consultant,
            preferences=_when_present(
                attributes,
                "preferences",
                [_preference(entry) for entry in attributes.preferences or []],
            ),
        )

    @classmethod
    def from_listing(cls, attributes: IntentionListItemAttributes) -> Self:
        return cls(id=attributes.id, date=attributes.date, updated_at=attributes.updated_at)


class InvestorIntentionsResponse(OmitNoneModel):
    """An investor's forward allocation intentions.

    Amounts are US dollars, not the millions used for AUM. A refusal is reported separately and
    means the Intentions & Preferences add-on is not licensed — an empty list does not.
    """

    investor_id: int = Field(description="With Intelligence investor identifier.")
    investor_name: str | None = Field(default=None, description="Resolved investor name.")
    intentions: list[IntentionResponse] = Field(
        default_factory=list, description="Intentions on this page, newest first."
    )
    total: int = Field(
        default=0, description="How many intentions With Intelligence holds in total."
    )
    returned: int = Field(default=0, description="Number of intentions returned on this page.")
    page: int = Field(default=1, description="Page number represented by this response.")
    has_more: bool = Field(
        default=False,
        description="True when another page is available. Call again with page + 1.",
    )


def _names(values: list[ClassificationAttributes] | None) -> list[str]:
    if values is None:
        return []
    return [value.name for value in values if value.name]


def _strategy_names(
    primary: ClassificationAttributes | None,
    secondary: list[ClassificationAttributes] | None,
) -> list[str]:
    names = [primary.name] if primary and primary.name else []
    names.extend(_names(secondary))
    return names


def _amount(attributes: IntentionAmountAttributes | None) -> IntentionAmountResponse | None:
    if attributes is None:
        return None
    if attributes.value_lower_usd is None and attributes.value_upper_usd is None:
        return None
    return IntentionAmountResponse(
        lower_usd=attributes.value_lower_usd,
        upper_usd=attributes.value_upper_usd,
    )


def _preference(attributes: IntentionPreferenceAttributes) -> IntentionPreferenceResponse:
    return IntentionPreferenceResponse(
        name=attributes.name,
        sentiment=attributes.sentiment,
        type=attributes.type,
    )


def _when_present[T](attributes: IntentionExtendedAttributes, field: str, value: T) -> T | None:
    return value if field in attributes.model_fields_set else None
