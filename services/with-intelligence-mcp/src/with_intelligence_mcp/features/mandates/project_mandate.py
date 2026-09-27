from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.features.mandates.api_responses import (
    MandateExtendedAttributes,
    MandateNoteAttributes,
)
from with_intelligence_mcp.features.mandates.responses import (
    MandateAmountResponse,
    MandateResponse,
)


def project_mandate(record: MandateExtendedAttributes) -> MandateResponse:
    latest = _latest_note(record)
    return MandateResponse(
        id=record.id,
        status=record.status.name if record.status else None,
        sub_status=(
            record.status.sub_status.name if record.status and record.status.sub_status else None
        ),
        service=record.service.name if record.service else None,
        amount=_amount(record),
        asset_classes=_names(record.asset_class),
        strategies=_names(record.primary_strategies) + _names(record.secondary_strategies),
        structures=_names(record.fund_structures),
        market_focuses=_names(record.market_focuses),
        awarded_to=record.fund.name if record.fund else None,
        consultant=record.consultant,
        consultant_firm=(
            record.primary_consultant_firm.name if record.primary_consultant_firm else None
        ),
        rfp_link=record.rfp_link,
        last_reviewed=record.last_reviewed.date if record.last_reviewed else None,
        updated_at=record.updated_at,
        note=record.note,
        latest_note=latest.note if latest else None,
        latest_note_date=latest.date if latest else None,
    )


def _names(values: list[ClassificationAttributes]) -> list[str]:
    return [value.name for value in values if value.name]


def _amount(record: MandateExtendedAttributes) -> MandateAmountResponse | None:
    amount = record.amount
    if amount is None or amount.amount is None:
        return None
    return MandateAmountResponse(
        value_millions=amount.amount,
        currency=amount.currency.short_name if amount.currency else None,
    )


def _latest_note(record: MandateExtendedAttributes) -> MandateNoteAttributes | None:
    """The most recent dated note. Undated notes lose to dated ones rather than sorting first."""
    dated = [entry for entry in record.notes if entry.date]
    if dated:
        return max(dated, key=lambda entry: entry.date or "")
    return record.notes[0] if record.notes else None
