from typing import cast

from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
from mcp_types import TextContent
from sqlalchemy import text

from architecture_demo_mcp.persistence import add_watchlist_entry
from architecture_demo_mcp.persistence import list_watchlist
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.persistence import WatchlistRefusal
from tests.conftest import ACME_DAILY_PRICES
from tests.conftest import CallTool
from tests.conftest import FakeTiingo


def _error_text(result: CallToolResult) -> str:
    assert result.is_error
    (content,) = result.content
    assert isinstance(content, TextContent)
    return content.text


async def test_the_server_discovers_every_tool(server: FastMCP) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()

    assert sorted(tool.name for tool in tools) == [
        "add_to_watchlist",
        "get_asset",
        "get_daily_prices",
        "get_quote",
        "get_watchlist",
        "remove_from_watchlist",
        "search_assets",
    ]


async def test_get_daily_prices_is_served_straight_from_the_spec(call_tool: CallTool) -> None:
    result = await call_tool("get_daily_prices", {"ticker": "ACME"})

    assert result.structured_content == {"result": ACME_DAILY_PRICES}


async def test_the_server_answers_one_client_after_another(call_tool: CallTool) -> None:
    """Each in-memory client enters the lifespan again, which must not close the shared client."""
    served = await call_tool("get_daily_prices", {"ticker": "ACME"})
    promoted = await call_tool("get_asset", {"ticker": "ACME"})

    assert not served.is_error
    assert not promoted.is_error


async def test_search_assets_drops_matches_without_a_ticker(
    call_tool: CallTool, tiingo: FakeTiingo
) -> None:
    result = await call_tool("search_assets", {"query": "acme"})

    assert result.structured_content == {
        "result": [
            {"ticker": "ACME", "name": "Acme Corporation", "asset_type": "Stock", "is_active": True}
        ]
    }
    (request,) = tiingo.requests
    assert dict(request.url.params) == {"query": "acme", "limit": "10"}
    assert request.headers["Authorization"] == "Token dummy-api-key"


async def test_get_asset_renames_the_vendor_fields(call_tool: CallTool) -> None:
    result = await call_tool("get_asset", {"ticker": " acme "})

    assert result.structured_content == {
        "ticker": "ACME",
        "name": "Acme Corporation",
        "description": "Makes anvils and rockets.",
        "exchange": "NASDAQ",
        "first_price_date": "1990-01-02",
        "last_price_date": "2026-10-19",
    }


async def test_get_quote_answers_a_second_ask_from_the_cache(
    call_tool: CallTool, tiingo: FakeTiingo
) -> None:
    first = await call_tool("get_quote", {"ticker": "ACME"})
    second = await call_tool("get_quote", {"ticker": "ACME"})

    expected = {
        "ticker": "ACME",
        "last_price": 101.25,
        "previous_close": 99.5,
        "as_of": "2026-10-20T14:30:00+00:00",
    }
    assert first.structured_content == expected
    assert second.structured_content == expected
    assert tiingo.paths() == ["/iex"]


async def test_get_quote_reports_a_ticker_iex_does_not_quote(call_tool: CallTool) -> None:
    result = await call_tool("get_quote", {"ticker": "ACMFX"})

    assert _error_text(result) == "IEX has no quote for ACMFX."


async def test_add_to_watchlist_stores_the_ticker(call_tool: CallTool) -> None:
    result = await call_tool(
        "add_to_watchlist", {"watchlist": "tech", "ticker": "acme", "note": "Earnings in May"}
    )

    assert result.structured_content is not None
    assert {**result.structured_content, "added_at": None} == {
        "watchlist": "tech",
        "ticker": "ACME",
        "name": "Acme Corporation",
        "exchange": "NASDAQ",
        "note": "Earnings in May",
        "added_at": None,
    }


async def test_add_to_watchlist_rejects_a_ticker_already_on_it(call_tool: CallTool) -> None:
    await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACME"})

    result = await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACME"})

    assert _error_text(result) == "ACME is already on tech."


async def test_add_to_watchlist_rejects_a_full_watchlist(
    call_tool: CallTool, persistence: Persistence
) -> None:
    for number in range(20):
        await add_watchlist_entry(
            persistence=persistence, watchlist="tech", ticker=f"T{number}", note=None, capacity=20
        )

    result = await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACME"})

    assert _error_text(result) == "tech already holds 20 tickers. Remove one first."


async def test_add_to_watchlist_rejects_an_unknown_ticker_without_storing_it(
    call_tool: CallTool,
) -> None:
    result = await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "NOPE"})
    watchlist = await call_tool("get_watchlist", {"watchlist": "tech"})

    assert "404 Not Found" in _error_text(result)
    assert watchlist.structured_content == {"result": []}


async def test_get_watchlist_lists_each_ticker_with_its_price(call_tool: CallTool) -> None:
    await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACME", "note": "Core"})
    await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACMFX"})

    result = await call_tool("get_watchlist", {"watchlist": "tech"})

    assert result.structured_content is not None
    listed = cast(list[dict[str, object]], result.structured_content["result"])
    watched = [
        {key: value for key, value in asset.items() if key != "added_at"} for asset in listed
    ]
    assert watched == [
        {"ticker": "ACME", "note": "Core", "last_price": 101.25, "previous_close": 99.5},
        {"ticker": "ACMFX", "note": None, "last_price": None, "previous_close": None},
    ]


async def test_get_watchlist_prices_every_ticker_in_one_request(
    call_tool: CallTool, tiingo: FakeTiingo
) -> None:
    await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACME"})
    await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACMFX"})
    tiingo.requests.clear()

    await call_tool("get_watchlist", {"watchlist": "tech"})

    (request,) = tiingo.requests
    assert request.url.path == "/iex"
    assert request.url.params["tickers"] == "ACME,ACMFX"


async def test_get_watchlist_asks_tiingo_only_for_the_tickers_not_cached(
    call_tool: CallTool, tiingo: FakeTiingo
) -> None:
    await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACME"})
    await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACMFX"})
    await call_tool("get_quote", {"ticker": "ACME"})
    tiingo.requests.clear()

    await call_tool("get_watchlist", {"watchlist": "tech"})

    (request,) = tiingo.requests
    assert request.url.params["tickers"] == "ACMFX"


async def test_remove_from_watchlist_takes_the_ticker_off(call_tool: CallTool) -> None:
    await call_tool("add_to_watchlist", {"watchlist": "tech", "ticker": "ACME"})

    removed = await call_tool("remove_from_watchlist", {"watchlist": "tech", "ticker": "acme"})
    again = await call_tool("remove_from_watchlist", {"watchlist": "tech", "ticker": "ACME"})
    watchlist = await call_tool("get_watchlist", {"watchlist": "tech"})

    assert removed.structured_content == {"watchlist": "tech", "ticker": "ACME", "removed": True}
    assert again.structured_content == {"watchlist": "tech", "ticker": "ACME", "removed": False}
    assert watchlist.structured_content == {"result": []}


async def test_adding_a_ticker_already_stored_stores_nothing(persistence: Persistence) -> None:
    await add_watchlist_entry(
        persistence=persistence, watchlist="tech", ticker="ACME", note="First", capacity=20
    )

    again = await add_watchlist_entry(
        persistence=persistence, watchlist="tech", ticker="ACME", note="Second", capacity=20
    )

    assert again is WatchlistRefusal.ALREADY_WATCHED
    [stored] = await list_watchlist(persistence=persistence, watchlist="tech")
    assert stored.note == "First"


async def test_an_unexpected_error_reaches_the_client_without_its_details(
    call_tool: CallTool, persistence: Persistence
) -> None:
    async with persistence.database() as session, session.begin():
        await session.execute(text("DROP TABLE watchlist_entries"))

    result = await call_tool("get_watchlist", {"watchlist": "tech"})

    assert "watchlist_entries" not in _error_text(result)


async def test_an_upstream_error_reaches_the_client(call_tool: CallTool) -> None:
    result = await call_tool("get_asset", {"ticker": "NOPE"})

    assert "404 Not Found" in _error_text(result)
