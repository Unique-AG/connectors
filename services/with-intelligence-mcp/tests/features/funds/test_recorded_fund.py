"""A recorded fund shape: string status ids, and regions delivered as a list."""

import json
import pathlib
from typing import cast

from with_intelligence_mcp.features.funds import FundExtendedAttributes, FundProfileResponse

_RECORDING = pathlib.Path(__file__).parent / "recordings" / "fund-extended.json"


def test_a_recorded_fund_parses_and_projects() -> None:
    body = cast("dict[str, object]", json.loads(_RECORDING.read_text()))
    record = FundExtendedAttributes.model_validate(body)
    assert [region.name for region in record.investment_regions or []] == ["Global"]
    assert [kind.name for kind in record.fund_type or []] == ["Single Manager"]

    projected = FundProfileResponse.from_attributes(record)
    assert projected.status == "Active"
    assert projected.sub_status == "Open to investment"
    assert projected.manager == "Example Manager"
    assert projected.investment_regions == ["Global"]
    assert projected.fund_types == ["Single Manager"]
    assert projected.minimum_investment == 10000000
    assert projected.minimum_investment_currency == "USD"
    assert projected.aum_millions == 500
    assert projected.lock_up is None
    assert projected.strategy == "Trades liquid markets."
    assert projected.domiciles == []
