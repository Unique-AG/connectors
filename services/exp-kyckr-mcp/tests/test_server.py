import asyncio

import httpx2
from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from kyckr_mcp.client import raise_for_kyckr_error
from kyckr_mcp.server import create_server
from kyckr_mcp.settings import Settings
from kyckr_mcp.tools import register_tools


def build_server(
    settings: Settings,
    spec: dict[str, object],
    upstream: httpx2.AsyncClient,
) -> FastMCP:
    mcp = create_server(settings, spec=spec, client=upstream)
    asyncio.run(register_tools(mcp, settings))
    return mcp


def run_tool(mcp: FastMCP, name: str, arguments: dict[str, object]) -> ToolResult:
    async def call() -> object:
        tool = await mcp.get_tool(name)
        assert tool is not None
        return await tool.run(arguments)

    return asyncio.run(call())  # type: ignore[return-value]


def test_generated_tools_are_overridden_and_internal_download_is_hidden(
    settings: Settings,
    spec: dict[str, object],
) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": []})

    upstream = httpx2.AsyncClient(
        base_url="https://test-api.kyckr.com/v2",
        transport=httpx2.MockTransport(handler),
    )
    try:
        mcp = build_server(settings, spec, upstream)
        names = {tool.name for tool in asyncio.run(mcp.list_tools())}
        assert names == {
            "search_companies",
            "get_lite_profile",
            "get_enhanced_profile",
            "list_company_documents",
            "create_document_order",
            "get_order",
            "list_orders",
        }
        search = asyncio.run(mcp.get_tool("search_companies"))
        assert search is not None
        assert set(search.parameters["properties"]) == {"name", "company_number", "iso_code"}
    finally:
        asyncio.run(upstream.aclose())


def test_search_wrapper_uses_original_openapi_arguments(
    settings: Settings,
    spec: dict[str, object],
) -> None:
    requests: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "correlationId": "search-correlation",
                "details": "Success",
                "data": [{"id": "GB|abc", "companyName": "Acme"}],
            },
        )

    upstream = httpx2.AsyncClient(
        base_url="https://test-api.kyckr.com/v2",
        transport=httpx2.MockTransport(handler),
    )
    try:
        result = run_tool(
            build_server(settings, spec, upstream),
            "search_companies",
            {"company_number": "123", "iso_code": "gb"},
        )
        assert result.structured_content == {
            "success": True,
            "correlationId": "search-correlation",
            "details": "Success",
            "data": [{"id": "GB|abc", "companyName": "Acme"}],
        }
        assert requests[0].url.params["companyNumber"] == "123"
        assert requests[0].url.params["isoCode"] == "GB"
    finally:
        asyncio.run(upstream.aclose())


def test_order_wrapper_inlines_json_and_strips_links(
    settings: Settings,
    spec: dict[str, object],
) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(
                200,
                json={
                    "correlationId": "order-correlation",
                    "details": "Success",
                    "data": {
                        "orderId": 123,
                        "status": "Success",
                        "links": {"document": "https://private.example/document"},
                    },
                },
            )
        return httpx2.Response(
            200,
            json={"Data": {"companyName": "Acme", "documentNumber": "D-1"}},
        )

    upstream = httpx2.AsyncClient(
        base_url="https://test-api.kyckr.com/v2",
        transport=httpx2.MockTransport(handler),
    )
    try:
        result = run_tool(
            build_server(settings, spec, upstream),
            "create_document_order",
            {"kyckr_id": "GB|abc", "product_id": "annual-accounts"},
        )
        assert result.structured_content == {
            "success": True,
            "correlationId": "order-correlation",
            "details": "Success",
            "data": {
                "orderId": 123,
                "status": "Success",
                "documentJson": {"companyName": "Acme", "documentNumber": "D-1"},
            },
        }
    finally:
        asyncio.run(upstream.aclose())


def test_api_errors_are_returned_as_structured_tool_responses(
    settings: Settings,
    spec: dict[str, object],
) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            json={"correlationId": "error-correlation", "data": {"detail": "Invalid company"}},
        )

    upstream = httpx2.AsyncClient(
        base_url="https://test-api.kyckr.com/v2",
        transport=httpx2.MockTransport(handler),
        event_hooks={"response": [raise_for_kyckr_error]},
    )
    try:
        result = run_tool(
            build_server(settings, spec, upstream),
            "search_companies",
            {"name": "Acme"},
        )
        assert result.structured_content == {
            "success": False,
            "statusCode": 400,
            "message": "Invalid company",
            "correlationId": "error-correlation",
        }
    finally:
        asyncio.run(upstream.aclose())


def test_order_without_upstream_details_omits_details_key(
    settings: Settings,
    spec: dict[str, object],
) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/download"):
            return httpx2.Response(200, json={"Data": {"companyName": "Acme"}})
        return httpx2.Response(200, json={"data": {"orderId": 7, "status": "Success"}})

    upstream = httpx2.AsyncClient(
        base_url="https://test-api.kyckr.com/v2",
        transport=httpx2.MockTransport(handler),
    )
    try:
        result = run_tool(build_server(settings, spec, upstream), "get_order", {"order_id": "7"})
        assert result.structured_content == {
            "success": True,
            "data": {"orderId": 7, "status": "Success", "documentJson": {"companyName": "Acme"}},
        }
    finally:
        asyncio.run(upstream.aclose())


def test_pdf_only_order_appends_notice_to_upstream_details(
    settings: Settings,
    spec: dict[str, object],
) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/download"):
            return httpx2.Response(404, json={"correlationId": "c", "data": {"detail": "none"}})
        return httpx2.Response(
            200, json={"details": "Success", "data": {"orderId": 7, "status": "Success"}}
        )

    upstream = httpx2.AsyncClient(
        base_url="https://test-api.kyckr.com/v2",
        transport=httpx2.MockTransport(handler),
        event_hooks={"response": [raise_for_kyckr_error]},
    )
    try:
        result = run_tool(build_server(settings, spec, upstream), "get_order", {"order_id": "7"})
        content = result.structured_content
        assert content is not None
        assert str(content["details"]).startswith("Success ")
        assert "only available as a PDF" in str(content["details"])
        assert "documentJson" not in content["data"]
    finally:
        asyncio.run(upstream.aclose())


def test_paid_tools_are_not_advertised_as_idempotent(
    settings: Settings,
    spec: dict[str, object],
) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": []})

    upstream = httpx2.AsyncClient(
        base_url="https://test-api.kyckr.com/v2",
        transport=httpx2.MockTransport(handler),
    )
    try:
        mcp = build_server(settings, spec, upstream)
        not_idempotent = {
            tool.name
            for tool in asyncio.run(mcp.list_tools())
            if tool.annotations and tool.annotations.idempotent_hint is False
        }
        assert not_idempotent == {
            "get_lite_profile",
            "get_enhanced_profile",
            "create_document_order",
        }
    finally:
        asyncio.run(upstream.aclose())
