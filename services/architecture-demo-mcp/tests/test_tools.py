from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import StaticTokenVerifier
import httpx2
from mcp_configs import ServerSettings
from mcp_types import TextContent

from architecture_demo_mcp.mcp import http_app
from architecture_demo_mcp.persistence import list_positions
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import UpstreamSettings
from tests.conftest import CallTool
from tests.conftest import FakeTiingo
from tests.offline_server import build_server

ACME_PERFORMANCE = {
    "ticker": "ACME",
    "first_date": "2026-10-14",
    "last_date": "2026-10-19",
    "trading_days": 4,
    "first_close": 100.0,
    "last_close": 121.0,
    "total_return": 0.21,
    "annualized_volatility": 2.582276,
    "max_drawdown": 0.1,
    "period_high": 122.0,
    "period_low": 98.0,
}


def _error_text(result: CallToolResult) -> str:
    assert result.is_error
    (content,) = result.content
    assert isinstance(content, TextContent)
    return content.text


async def test_the_server_serves_the_spec_operations_and_its_own_tools(server: FastMCP) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()

    assert sorted(tool.name for tool in tools) == [
        "get_crypto_prices",
        "get_crypto_top_of_book",
        "get_daily_meta",
        "get_daily_prices",
        "get_forex_top_of_book",
        "get_fundamentals_daily",
        "get_fundamentals_meta",
        "get_fundamentals_statements",
        "get_iex_top_of_book",
        "get_price_performance",
        "get_ticker_distributions",
        "get_ticker_splits",
        "list_news",
        "record_position",
        "search_assets",
    ]


async def test_a_served_operation_answers_straight_from_the_spec(
    call_tool: CallTool, tiingo: FakeTiingo
) -> None:
    result = await call_tool("search_assets", {"query": "acme"})

    assert result.structured_content == {"result": [{"ticker": "ACME", "name": "Acme Corporation"}]}
    (request,) = tiingo.requests
    assert request.headers["Authorization"] == "Token dummy-api-key"


async def test_get_price_performance_summarizes_the_period(call_tool: CallTool) -> None:
    result = await call_tool(
        "get_price_performance",
        {"ticker": " acme ", "start_date": "2026-10-14", "end_date": "2026-10-19"},
    )

    assert result.structured_content == ACME_PERFORMANCE


async def test_get_price_performance_answers_a_second_ask_from_the_cache(
    call_tool: CallTool, tiingo: FakeTiingo
) -> None:
    arguments: dict[str, object] = {
        "ticker": "ACME",
        "start_date": "2026-10-14",
        "end_date": "2026-10-19",
    }

    first = await call_tool("get_price_performance", arguments)
    second = await call_tool("get_price_performance", arguments)

    assert first.structured_content == second.structured_content == ACME_PERFORMANCE
    assert tiingo.paths() == ["/tiingo/daily/ACME/prices"]


async def test_get_price_performance_rejects_a_period_that_ends_before_it_starts(
    call_tool: CallTool, tiingo: FakeTiingo
) -> None:
    result = await call_tool(
        "get_price_performance",
        {"ticker": "ACME", "start_date": "2026-10-19", "end_date": "2026-10-14"},
    )

    assert _error_text(result) == "The period ends on 2026-10-14, before 2026-10-19."
    assert tiingo.requests == []


async def test_get_price_performance_needs_two_trading_days(call_tool: CallTool) -> None:
    result = await call_tool(
        "get_price_performance",
        {"ticker": "ACME", "start_date": "2026-10-19", "end_date": "2026-10-19"},
    )

    assert _error_text(result) == (
        "Tiingo has 1 trading day(s) of ACME in the period, and a performance needs at least 2."
    )


async def test_record_position_values_the_whole_portfolio(call_tool: CallTool) -> None:
    await call_tool(
        "record_position",
        {"portfolio": "core", "ticker": "acme", "quantity": 10, "cost_basis": 100},
    )
    result = await call_tool(
        "record_position",
        {"portfolio": "core", "ticker": "GLOBEX", "quantity": 5, "cost_basis": 50},
    )

    assert result.structured_content == {
        "portfolio": "core",
        "positions": [
            {
                "ticker": "ACME",
                "quantity": 10.0,
                "cost_basis": 100.0,
                "last_close": 120.0,
                "last_close_date": "2026-10-20",
                "market_value": 1200.0,
                "unrealized_pnl": 200.0,
                "weight": 0.857143,
            },
            {
                "ticker": "GLOBEX",
                "quantity": 5.0,
                "cost_basis": 50.0,
                "last_close": 40.0,
                "last_close_date": "2026-10-20",
                "market_value": 200.0,
                "unrealized_pnl": -50.0,
                "weight": 0.142857,
            },
        ],
        "cost": 1250.0,
        "market_value": 1400.0,
        "unrealized_pnl": 150.0,
        "unrealized_return": 0.12,
    }


async def test_record_position_replaces_an_earlier_holding(
    call_tool: CallTool, persistence: Persistence
) -> None:
    await call_tool(
        "record_position",
        {"portfolio": "core", "ticker": "ACME", "quantity": 10, "cost_basis": 100},
    )
    await call_tool(
        "record_position",
        {"portfolio": "core", "ticker": "ACME", "quantity": 4, "cost_basis": 90},
    )

    (position,) = await list_positions(persistence=persistence, owner="local", portfolio="core")
    assert (position.ticker, position.quantity, position.cost_basis) == ("ACME", 4.0, 90.0)


async def test_record_position_rejects_a_ticker_tiingo_never_priced(
    call_tool: CallTool, persistence: Persistence
) -> None:
    result = await call_tool(
        "record_position",
        {"portfolio": "core", "ticker": "UNPRX", "quantity": 1, "cost_basis": 10},
    )

    assert _error_text(result) == (
        "Tiingo has no prices for UNPRX, so a position in it cannot be valued."
    )
    assert await list_positions(persistence=persistence, owner="local", portfolio="core") == []


async def test_a_signed_in_caller_owns_the_positions_it_records(
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    server_settings: ServerSettings,
    persistence: Persistence,
) -> None:
    signed_in = StaticTokenVerifier(
        tokens={"token-a": {"client_id": "client", "scopes": [], "sub": "owner-a"}}
    )
    server = build_server(upstream_settings, persistence, upstream_transport, auth=signed_in)
    app = http_app(server, server_settings)

    def over_asgi(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        follow_redirects: bool = False,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=follow_redirects,
        )

    transport = StreamableHttpTransport(
        f"{server_settings.base_url}/mcp", auth="token-a", httpx_client_factory=over_asgi
    )
    async with app.router.lifespan_context(app), Client(transport) as client:
        await client.call_tool(
            "record_position",
            {"portfolio": "core", "ticker": "ACME", "quantity": 1, "cost_basis": 100},
        )

    owned = await list_positions(persistence=persistence, owner="owner-a", portfolio="core")
    assert [position.ticker for position in owned] == ["ACME"]
    assert await list_positions(persistence=persistence, owner="local", portfolio="core") == []
