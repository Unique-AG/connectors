"""`BackfillOpportunityStageHistoryInput`: cap and required fields."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.opportunity_writes import (
    MAX_STAGE_HISTORY_RECORDS,
    BackfillOpportunityStageHistoryInput,
)

_ADAPTER: TypeAdapter[BackfillOpportunityStageHistoryInput] = TypeAdapter(
    BackfillOpportunityStageHistoryInput
)


def _record(opportunity_id: str = "5755101") -> dict[str, object]:
    return {
        "opportunity_id": opportunity_id,
        "stage": "IDD",
        "effective_date": "2026-02-01",
    }


def test_accepts_one_record() -> None:
    parsed = _ADAPTER.validate_python({"records": [_record()]})

    assert len(parsed.records) == 1
    assert parsed.records[0].stage == "IDD"


def test_over_the_cap_is_rejected_by_the_input_model() -> None:
    records = [_record(str(index)) for index in range(MAX_STAGE_HISTORY_RECORDS + 1)]

    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"records": records})
