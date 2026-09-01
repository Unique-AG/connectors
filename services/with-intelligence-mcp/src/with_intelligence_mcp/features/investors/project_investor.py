from with_intelligence_mcp.features.investors.api_responses import (
    ClassificationAttributes,
    EntityAttributes,
    InvestorExtendedAttributes,
)
from with_intelligence_mcp.features.investors.responses import (
    AumResponse,
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
        capital_structures=_named(record.investment_capital_structures),
        managers=_named(record.managers),
        consultants=_named(record.consultants),
        contacts=[NamedValueResponse(id=c.id, name=c.name) for c in record.contacts],
        contacts_total=record.contacts_total,
        preferences_available=bool(record.preferences),
        preferences=record.preferences or None,
    )


def _named(values: list[ClassificationAttributes]) -> list[NamedValueResponse]:
    return [NamedValueResponse(id=value.id, name=value.name) for value in values]


def _location(record: InvestorExtendedAttributes) -> str | None:
    if record.address is None:
        return None
    parts = [record.address.city, record.address.state, record.address.country]
    populated = [part for part in parts if part]
    return ", ".join(populated) or None


def _aum(record: InvestorExtendedAttributes) -> AumResponse | None:
    latest = record.latest_aum
    if latest is not None and latest.value is not None:
        currency = latest.currency or (record.currency.name if record.currency else None)
        return AumResponse(value=latest.value, as_of=latest.date, currency=currency)
    if record.aum is not None:
        return AumResponse(
            value=record.aum, currency=record.currency.name if record.currency else None
        )
    return None


def _entity_names(values: list[EntityAttributes]) -> list[str]:
    return [value.name for value in values if value.name]
