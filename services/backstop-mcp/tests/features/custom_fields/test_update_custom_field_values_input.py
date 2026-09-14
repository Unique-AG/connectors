"""`UpdateCustomFieldValuesInput`: cap and required fields."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.custom_fields import (
    MAX_CUSTOM_FIELD_VALUES,
    UpdateCustomFieldValuesInput,
)

_ADAPTER: TypeAdapter[UpdateCustomFieldValuesInput] = TypeAdapter(UpdateCustomFieldValuesInput)


def _value(definition_id: int = 9823191) -> dict[str, object]:
    return {"definition_id": definition_id, "value": "Direct"}


def test_accepts_one_value() -> None:
    parsed = _ADAPTER.validate_python(
        {"entity_type": "people", "entity_id": "1", "values": [_value()]}
    )

    assert len(parsed.values) == 1
    assert parsed.entity_type == "people"


def test_over_the_cap_is_rejected_by_the_input_model() -> None:
    values = [_value(index) for index in range(MAX_CUSTOM_FIELD_VALUES + 1)]

    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"entity_type": "people", "entity_id": "1", "values": values})
