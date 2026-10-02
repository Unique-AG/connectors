"""Service providers arrive as lists, and AUM stays in millions."""

import json
import pathlib
from typing import cast

from with_intelligence_mcp.features.managers import (
    ManagerExtendedAttributes,
    ManagerProfileResponse,
)

_RECORDING = pathlib.Path(__file__).parent / "recordings" / "manager-extended.json"


def test_a_recorded_manager_parses_provider_lists() -> None:
    body = cast("dict[str, object]", json.loads(_RECORDING.read_text()))
    record = ManagerExtendedAttributes.model_validate(body)
    assert [provider.name for provider in record.administrator or []] == ["State Street"]

    projected = ManagerProfileResponse.from_attributes(record)
    assert projected.location == "Westport, United States"
    assert projected.administrators == ["State Street"]
    assert projected.prime_brokers == ["JP Morgan"]
    assert projected.aums is not None
    assert projected.aums[0].value_millions == 85000
    assert projected.aums[0].is_estimate is True
    assert projected.summary == "A global macro firm. Risk parity's home."
