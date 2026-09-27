from with_intelligence_mcp.features.investments.api_responses import (
    InvestmentExtendedAttributes,
)
from with_intelligence_mcp.features.investments.responses import (
    PositionAmountResponse,
    PositionResponse,
)
from with_intelligence_mcp.features.investors import ClassificationAttributes


def project_position(record: InvestmentExtendedAttributes) -> PositionResponse:
    return PositionResponse(
        id=record.id,
        fund=record.fund.name if record.fund else None,
        fund_id=record.fund.id if record.fund else None,
        manager=record.manager_firm.name if record.manager_firm else None,
        manager_id=record.manager_firm.id if record.manager_firm else None,
        amount=_amount(record),
        asset_classes=_names(record.asset_classes),
        strategies=_names(record.fund_primary_strategies)
        + _names(record.fund_secondary_strategies),
        structures=_names(record.fund_structures),
        as_of=record.latest_as_of,
        is_current=not record.deleted_at,
        exited_on=record.deleted_at,
        fund_unidentified=record.fund.unknown if record.fund else None,
    )


def _names(values: list[ClassificationAttributes]) -> list[str]:
    return [value.name for value in values if value.name]


def _amount(record: InvestmentExtendedAttributes) -> PositionAmountResponse | None:
    """Same units as everywhere else in this API: millions."""
    amount = record.amount
    if amount is None or amount.amount is None:
        return None
    return PositionAmountResponse(
        value_millions=amount.amount,
        as_of=amount.date,
        currency=amount.currency.short_name if amount.currency else None,
    )
