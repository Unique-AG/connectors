"""What the tool returns to the model: trimmed, renamed where With Intelligence's naming misleads,
and documented for the model that reads it."""

from typing import Literal, Self

from pydantic import Field

from with_intelligence_mcp.features.investors.api_responses import (
    ClassificationAttributes,
    ConsultantAttributes,
    EntityAttributes,
    InvestorExtendedAttributes,
    StrategyGroupAttributes,
)
from with_intelligence_mcp.models import OmitNoneModel
from with_intelligence_mcp.utils import html_to_markdown


class NamedValueResponse(OmitNoneModel):
    id: int | None = Field(
        default=None, description="With Intelligence's id, for follow-up filters."
    )
    name: str | None = None


class AssetsUnderManagementResponse(OmitNoneModel):
    value_millions: float | None = Field(
        default=None,
        description=(
            "Total assets under management, in MILLIONS of `currency`. 135900 means 135.9 "
            "billion. Do not report it as a plain figure."
        ),
    )
    value_usd_millions: float | None = Field(
        default=None, description="The same figure in millions of USD."
    )
    band: str | None = Field(
        default=None, description="With Intelligence's own words for the size, e.g. '> $50bn'."
    )
    as_of: str | None = Field(default=None, description="Date the figure was reported.")
    currency: str | None = None


class StrategyGroupResponse(OmitNoneModel):
    """A primary strategy with the secondaries recorded under it."""

    primary: str | None = None
    secondary: list[str] = Field(default_factory=list)


class ConsultantResponse(OmitNoneModel):
    id: int | None = None
    name: str | None = None
    is_lead: bool | None = Field(
        default=None, description="Whether this consultant leads the relationship."
    )
    role: str | None = None


class InvestorProfileResponse(OmitNoneModel):
    """One institutional investor, as a meeting-prep sheet.

    `managers` is who they currently allocate to. A field that is absent is unknown to With
    Intelligence, not zero.
    """

    id: int
    name: str | None = None
    investor_type: str | None = None
    summary: str | None = None
    profile: str | None = None
    website: str | None = None
    founded: int | None = None
    location: str | None = None
    aum: AssetsUnderManagementResponse | None = None
    updated_at: str | None = None

    asset_classes: list[NamedValueResponse] | None = None
    strategies: list[StrategyGroupResponse] | None = Field(
        default=None,
        description=(
            "What they allocate to, grouped: each primary strategy with the secondaries "
            "recorded under it. Prefer this over the flat lists below, which mix every asset "
            "class's strategies together."
        ),
    )
    primary_strategies: list[NamedValueResponse] | None = None
    secondary_strategies: list[NamedValueResponse] | None = None
    investment_regions: list[NamedValueResponse] | None = None
    investment_countries: list[NamedValueResponse] | None = None
    fund_structures: list[NamedValueResponse] | None = None
    instruments: list[NamedValueResponse] | None = None
    capital_structure_ids: list[int] | None = Field(
        default=None,
        description="Ids only — the API returns no names for capital structures here.",
    )

    managers: list[NamedValueResponse] | None = None
    consultants: list[ConsultantResponse] | None = None

    contacts_total: int | None = Field(
        default=None, description="How many contacts With Intelligence holds for this investor."
    )
    contact_ids: list[int] | None = Field(
        default=None,
        description=(
            "Every contact the investor record lists, as ids — the API returns no names here, "
            "so names, titles and seniority require a separate person lookup."
        ),
    )

    preferences_available: bool = Field(
        default=False,
        description=(
            "Whether stated allocation preferences came back. False means this subscription "
            "does not include the Intentions & Preferences add-on — NOT that the investor has "
            "stated no preferences."
        ),
    )
    preferences: dict[str, object] | None = None

    @classmethod
    def from_attributes(cls, attributes: InvestorExtendedAttributes) -> Self:
        return cls(
            id=attributes.id,
            name=attributes.name,
            investor_type=attributes.type.name if attributes.type else None,
            summary=html_to_markdown(attributes.summary),
            profile=html_to_markdown(attributes.family_profile),
            website=attributes.website,
            founded=attributes.year_of_incorporation,
            location=_location(attributes),
            aum=_assets_under_management(attributes),
            updated_at=attributes.updated_at,
            asset_classes=_when_present(
                attributes, "asset_classes", _named(attributes.asset_classes)
            ),
            strategies=_when_present(
                attributes,
                "investment_strategies",
                [_strategy_group(group) for group in attributes.investment_strategies],
            ),
            primary_strategies=_when_present(
                attributes, "primary_strategies", _named(attributes.primary_strategies)
            ),
            secondary_strategies=_when_present(
                attributes, "secondary_strategies", _named(attributes.secondary_strategies)
            ),
            investment_regions=_when_present(
                attributes, "investment_regions", _named(attributes.investment_regions)
            ),
            investment_countries=_when_present(
                attributes, "investment_countries", _named(attributes.investment_countries)
            ),
            fund_structures=_when_present(
                attributes,
                "investment_fund_structures",
                _named(attributes.investment_fund_structures),
            ),
            instruments=_when_present(
                attributes,
                "investment_instruments",
                _named(attributes.investment_instruments),
            ),
            capital_structure_ids=_when_present(
                attributes,
                "investment_capital_structures",
                _ids(attributes.investment_capital_structures),
            ),
            managers=_when_present(attributes, "managers", _named(attributes.managers)),
            consultants=_when_present(
                attributes,
                "consultants",
                [_consultant(entry) for entry in attributes.consultants],
            ),
            contacts_total=attributes.contacts_total,
            contact_ids=_when_present(attributes, "contacts", _ids(attributes.contacts)),
            preferences_available="preferences" in attributes.model_fields_set,
            preferences=attributes.preferences,
        )


class InvestorCandidateResponse(OmitNoneModel):
    id: int
    name: str | None = None
    updated_at: str | None = None


class InvestorAmbiguousResponse(OmitNoneModel):
    """Several investors matched the name. Ask which one, then call again with `investor_id`."""

    status: Literal["ambiguous"] = "ambiguous"
    searched_for: str
    candidates: list[InvestorCandidateResponse] = Field(default_factory=list)
    total_matches: int = 0


class InvestorNotFoundResponse(OmitNoneModel):
    """Nothing matched. The name filter may need to be closer to the investor's registered name."""

    status: Literal["not_found"] = "not_found"
    searched_for: str
    hint: str | None = None


class InvestorNotEntitledResponse(OmitNoneModel):
    status: Literal["not_entitled"] = "not_entitled"
    searched_for: str
    hint: str | None = None


def _when_present[T](attributes: InvestorExtendedAttributes, field: str, value: T) -> T | None:
    return value if field in attributes.model_fields_set else None


def _strategy_group(attributes: StrategyGroupAttributes) -> StrategyGroupResponse:
    return StrategyGroupResponse(
        primary=attributes.primary_strategy.name if attributes.primary_strategy else None,
        secondary=[entry.name for entry in attributes.secondary_strategies if entry.name],
    )


def _named(values: list[ClassificationAttributes]) -> list[NamedValueResponse]:
    return [NamedValueResponse(id=value.id, name=value.name) for value in values]


def _ids(values: list[EntityAttributes]) -> list[int]:
    return [value.id for value in values if value.id is not None]


def _consultant(attributes: ConsultantAttributes) -> ConsultantResponse:
    return ConsultantResponse(
        id=attributes.id,
        name=attributes.name,
        is_lead=attributes.is_lead,
        role=attributes.role_extended,
    )


def _location(attributes: InvestorExtendedAttributes) -> str | None:
    address = attributes.address
    if address is None:
        return None
    parts = [
        address.city,
        address.state.name if address.state else None,
        address.country.name if address.country else None,
    ]
    return ", ".join(part for part in parts if part) or None


def _assets_under_management(
    attributes: InvestorExtendedAttributes,
) -> AssetsUnderManagementResponse | None:
    currency = attributes.currency.short_name if attributes.currency else None
    latest = attributes.latest_aum
    if latest is not None and (latest.value is not None or latest.value_usd is not None):
        bands = [entry.label for entry in latest.ranges_usd if entry.label]
        return AssetsUnderManagementResponse(
            value_millions=latest.value,
            value_usd_millions=latest.value_usd,
            band=bands[0] if bands else None,
            as_of=latest.as_of,
            currency=currency,
        )
    if attributes.aum is not None:
        return AssetsUnderManagementResponse(value_millions=attributes.aum, currency=currency)
    return None
