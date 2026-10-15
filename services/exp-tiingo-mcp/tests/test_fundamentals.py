import asyncio
from functools import partial
from typing import Any, get_args

import httpx2
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tiingo_mcp import server
from tiingo_mcp.models.vendor_responses import FundamentalsStatementData
from tiingo_mcp.server import create_server
from tiingo_mcp.settings import Settings
from tiingo_mcp.tools.fundamentals import Section


def statement(
    date: str, year: int, quarter: int, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    default = {
        "overview": [{"dataCode": "roe", "value": 0.1}],
        "incomeStatement": [{"dataCode": "revenue", "value": 100.0 + quarter}],
        "balanceSheet": [{"dataCode": "assets", "value": 500.0}],
        "cashFlow": [{"dataCode": "ncfo", "value": 20.0}],
    }
    return {"date": date, "year": year, "quarter": quarter, "statementData": data or default}


ROWS = [
    statement("2025-03-31T00:00:00.000Z", 2025, 1),
    statement("2024-12-31T00:00:00.000Z", 2024, 0),
    statement("2024-12-31T00:00:00.000Z", 2024, 4),
    statement("2024-09-30T00:00:00.000Z", 2024, 3),
    statement("2024-06-30T00:00:00.000Z", 2024, 2),
    statement("2024-03-31T00:00:00.000Z", 2024, 1),
]


def call(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    args: dict[str, Any],
    body: object,
) -> Any:  # noqa: ANN401
    """Run `tool` through the server with Tiingo answering `body`; returns the structured result."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=body)

    monkeypatch.setattr(
        server.httpx2,
        "AsyncClient",
        partial(httpx2.AsyncClient, transport=httpx2.MockTransport(handler)),
    )

    async def run() -> Any:  # noqa: ANN401
        mcp = create_server(settings)
        async with Client(mcp) as client:
            return (await client.call_tool(tool, args)).structured_content["result"]

    return asyncio.run(run())


def test_section_matches_the_generated_statement_sections() -> None:
    assert set(get_args(Section)) == set(FundamentalsStatementData.model_fields)


def test_recent_financials_is_newest_first_and_skips_annual_rows(
    local_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = call(
        local_settings, monkeypatch, "recent_financials", {"ticker": "ABC"}, list(reversed(ROWS))
    )
    assert [(p["year"], p["quarter"]) for p in result] == [
        (2025, 1),
        (2024, 4),
        (2024, 3),
        (2024, 2),
    ]
    assert result[0]["statements"]["incomeStatement"] == {"revenue": 101.0}


def test_recent_financials_cuts_off_at_periods(
    local_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = call(
        local_settings, monkeypatch, "recent_financials", {"ticker": "ABC", "periods": 2}, ROWS
    )
    assert [(p["year"], p["quarter"]) for p in result] == [(2025, 1), (2024, 4)]


def test_recent_financials_keeps_an_explicit_empty_section_list(
    local_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = call(
        local_settings,
        monkeypatch,
        "recent_financials",
        {"ticker": "ABC", "periods": 1, "sections": []},
        ROWS,
    )
    assert result[0]["statements"] == {}


def test_recent_financials_limits_output_to_the_requested_sections(
    local_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = {"ticker": "ABC", "periods": 1, "sections": ["balanceSheet", "cashFlow"]}
    result = call(local_settings, monkeypatch, "recent_financials", args, ROWS)
    assert result[0]["statements"] == {
        "balanceSheet": {"assets": 500.0},
        "cashFlow": {"ncfo": 20.0},
    }


def test_recent_financials_tolerates_missing_statement_data_and_sections(
    local_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        statement("2025-03-31T00:00:00.000Z", 2025, 1, {"overview": [{"dataCode": "roe"}]}),
        {"date": "2024-12-31T00:00:00.000Z", "year": 2024, "quarter": 4, "statementData": None},
    ]
    result = call(local_settings, monkeypatch, "recent_financials", {"ticker": "ABC"}, rows)
    assert result[0]["statements"] == {
        "overview": {"roe": None},
        "incomeStatement": {},
        "balanceSheet": {},
        "cashFlow": {},
    }
    assert result[1]["statements"] == {
        section: {} for section in ("overview", "incomeStatement", "balanceSheet", "cashFlow")
    }


@pytest.mark.parametrize("periods", [0, 21])
def test_recent_financials_rejects_out_of_range_periods(
    local_settings: Settings, monkeypatch: pytest.MonkeyPatch, periods: int
) -> None:
    with pytest.raises(ToolError, match=r"\nperiods\n"):
        call(
            local_settings,
            monkeypatch,
            "recent_financials",
            {"ticker": "ABC", "periods": periods},
            ROWS,
        )


def test_recent_valuation_metrics_passes_explicit_nulls_through(
    local_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [{"date": "2025-03-31T00:00:00.000Z", "marketCap": 1.5e9, "peRatio": None}]
    result = call(local_settings, monkeypatch, "recent_valuation_metrics", {"ticker": "ABC"}, rows)
    assert result[0]["marketCap"] == 1.5e9
    assert "peRatio" in result[0] and result[0]["peRatio"] is None


@pytest.mark.parametrize(
    ("tool", "args", "field"),
    [
        ("recent_daily_prices", {"ticker": "ABC", "lookback_days": 400}, "lookback_days"),
        ("recent_valuation_metrics", {"ticker": "ABC", "lookback_days": 0}, "lookback_days"),
        ("recent_financials", {"ticker": "ABC", "sections": ["nope"]}, "sections.0"),
    ],
)
def test_bad_arguments_name_the_field(
    local_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    args: dict[str, Any],
    field: str,
) -> None:
    with pytest.raises(ToolError, match=rf"\n{field}\n"):
        call(local_settings, monkeypatch, tool, args, [])


def test_a_response_that_does_not_fit_its_model_is_reported_as_such(
    local_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ToolError, match=r"Unexpected response: 0\.date: "):
        call(local_settings, monkeypatch, "recent_daily_prices", {"ticker": "ABC"}, [{"date": 5}])
