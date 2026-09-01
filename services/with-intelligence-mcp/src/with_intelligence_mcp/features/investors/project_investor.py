from with_intelligence_mcp.features.investors.api_responses import (
    ClassificationAttributes,
    ConsultantAttributes,
    EntityAttributes,
    InvestorExtendedAttributes,
)
from with_intelligence_mcp.features.investors.responses import (
    AumResponse,
    ConsultantResponse,
    InvestorProfileResponse,
    NamedValueResponse,
)


def project_investor(record: InvestorExtendedAttributes) -> InvestorProfileResponse:
    """Turn the vendor's record into the shape the tool publishes."""
    return InvestorProfileResponse(
        id=record.id,
        name=record.name,
        investor_type=record.type.name if record.type else None,
        summary=record.summary,
        profile=record.family_profile,
        website=record.website,
        founded=record.year_of_incorporation,
        location=_location(record),
        aum=_aum(record),
        updated_at=record.updated_at,
        asset_classes=_named(record.asset_classes),
        primary_strategies=_named(record.primary_strategies),
        secondary_strategies=_named(record.secondary_strategies),
        investment_regions=_named(record.investment_regions),
        investment_countries=_named(record.investment_countries),
        fund_structures=_named(record.investment_fund_structures),
        instruments=_named(record.investment_instruments),
        capital_structure_ids=_ids(record.investment_capital_structures),
        managers=_named(record.managers),
        consultants=[_consultant(entry) for entry in record.consultants],
        contacts_total=record.contacts_total,
        contact_ids=_ids(record.contacts),
        preferences_available=bool(record.preferences),
        preferences=record.preferences or None,
    )


def _named(values: list[ClassificationAttributes]) -> list[NamedValueResponse]:
    return [NamedValueResponse(id=value.id, name=value.name) for value in values]


def _ids(values: list[EntityAttributes]) -> list[int]:
    return [value.id for value in values if value.id is not None]


def _consultant(entry: ConsultantAttributes) -> ConsultantResponse:
    return ConsultantResponse(
        id=entry.id, name=entry.name, is_lead=entry.is_lead, role=entry.role_extended
    )


def _location(record: InvestorExtendedAttributes) -> str | None:
    """City, state, country — the last two arrive as objects, not strings."""
    address = record.address
    if address is None:
        return None
    parts = [
        address.city,
        address.state.name if address.state else None,
        address.country.name if address.country else None,
    ]
    return ", ".join(part for part in parts if part) or None


def _aum(record: InvestorExtendedAttributes) -> AumResponse | None:
    """Prefer the dated figure. `latest_aum` carries no currency, so that comes off the record."""
    currency = record.currency.short_name if record.currency else None
    latest = record.latest_aum
    if latest is not None and (latest.value is not None or latest.value_usd is not None):
        return AumResponse(
            value=latest.value,
            value_usd=latest.value_usd,
            as_of=latest.as_of,
            currency=currency,
        )
    if record.aum is not None:
        return AumResponse(value=record.aum, currency=currency)
    return None
