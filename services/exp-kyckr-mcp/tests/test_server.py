import asyncio
from typing import Any

import httpx2
import pytest
from fastmcp import Client
from mcp.types import Tool

from kyckr_mcp import server
from kyckr_mcp.settings import Settings
from tests.support import build_server, call_tool

TOOLS = {
    "search_companies",
    "get_lite_profile",
    "get_enhanced_profile",
    "list_company_documents",
    "create_document_order",
    "get_order",
    "list_orders",
}
FREE_READ = (True, False, True, True)
PAID_READ = (True, False, False, True)
PAID_ORDER = (False, False, False, True)
# read-only, destructive, idempotent and open-world hints, as the TypeScript service sets them
HINTS = {
    "search_companies": FREE_READ,
    "get_lite_profile": PAID_READ,
    "get_enhanced_profile": PAID_READ,
    "list_company_documents": FREE_READ,
    "create_document_order": PAID_ORDER,
    "get_order": FREE_READ,
    "list_orders": FREE_READ,
}
# fields every tool must publish under `data`, so a typed schema cannot shrink to an object
DATA_FIELDS = {
    "search_companies": {"id", "companyName"},
    "get_lite_profile": {"companyName", "address"},
    "get_enhanced_profile": {"status", "orderId"},
    "list_company_documents": {"id", "name", "cost"},
    "create_document_order": {"orderId", "status", "documentJson"},
    "get_order": {"orderId", "status", "documentJson"},
    "list_orders": {"orders", "pageNumber", "orderId"},
}


async def empty(_request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json={"data": []})


def list_tools(settings: Settings) -> dict[str, Tool]:
    async def run() -> dict[str, Tool]:
        async with Client(build_server(settings, empty)) as client:
            return {tool.name: tool for tool in await client.list_tools()}

    return asyncio.run(run())


def data_fields(output: dict[str, Any]) -> set[str]:
    definitions = output.get("$defs", {})

    def fields(node: dict[str, Any]) -> set[str]:
        if "$ref" in node:
            return fields(definitions[node["$ref"].rsplit("/", 1)[-1]])
        if "items" in node:
            return fields(node["items"])
        for key in ("anyOf", "oneOf"):
            if key in node:
                return set().union(*(fields(option) for option in node[key]))
        return set(node.get("properties", {}))

    return fields(output["properties"]["data"])


def test_the_server_serves_the_seven_tools(settings: Settings) -> None:
    assert set(list_tools(settings)) == TOOLS


def test_search_publishes_the_snake_case_arguments_of_the_platform(settings: Settings) -> None:
    search = list_tools(settings)["search_companies"]
    assert set(search.input_schema["properties"]) == {"name", "company_number", "iso_code"}


def test_the_iso_code_is_checked_in_the_schema_clients_see(settings: Settings) -> None:
    iso_code = list_tools(settings)["search_companies"].input_schema["properties"]["iso_code"]
    assert iso_code["anyOf"] == [{"type": "string", "pattern": "^[A-Za-z]{2}$"}, {"type": "null"}]


def test_every_tool_has_a_title_an_icon_and_a_system_prompt(settings: Settings) -> None:
    for name, tool in list_tools(settings).items():
        assert tool.title, name
        assert tool.annotations and tool.annotations.title == tool.title, name
        assert tool.meta
        assert tool.meta["unique.app/icon"] and tool.meta["unique.app/system-prompt"], name


def test_system_prompts_use_the_argument_names_the_tools_take(settings: Settings) -> None:
    for name, tool in list_tools(settings).items():
        prompt = str((tool.meta or {})["unique.app/system-prompt"]).replace("data.orderId", "")
        for camel in ("kyckrId", "isoCode", "orderId", "productId"):
            assert camel not in prompt, (name, camel)


def test_every_tool_publishes_the_typed_data_the_platform_reads(settings: Settings) -> None:
    for name, tool in list_tools(settings).items():
        output = tool.output_schema
        assert output is not None, name
        assert output["required"] == ["success"], name
        assert DATA_FIELDS[name] <= data_fields(output), name
    order = data_fields(list_tools(settings)["get_order"].output_schema or {})
    assert "links" not in order


def test_every_tool_sets_the_hints_the_typescript_service_sets(settings: Settings) -> None:
    hints = {
        name: (
            tool.annotations.read_only_hint,
            tool.annotations.destructive_hint,
            tool.annotations.idempotent_hint,
            tool.annotations.open_world_hint,
        )
        for name, tool in list_tools(settings).items()
        if tool.annotations
    }
    assert hints == HINTS


def test_the_server_refuses_to_start_when_an_operation_it_calls_is_not_in_the_spec(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "CLIENT_BACKED", [*server.CLIENT_BACKED, "get-nowhere"])

    async def start() -> None:
        async with Client(build_server(settings, empty)):
            pass

    with pytest.raises(Exception, match="not in the spec"):
        asyncio.run(start())


def test_a_server_can_run_two_sessions_one_after_the_other(settings: Settings) -> None:
    server = build_server(settings, empty)

    async def sessions() -> list[int]:
        counts: list[int] = []
        for _ in range(2):
            async with Client(server) as client:
                counts.append(len(await client.list_tools()))
        return counts

    assert asyncio.run(sessions()) == [7, 7]


def test_search_sends_the_arguments_kyckr_expects_and_answers_without_empty_fields(
    settings: Settings,
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

    result = call_tool(
        settings, handler, "search_companies", {"company_number": " 123 ", "iso_code": "gb"}
    )

    assert result.structured_content == {
        "success": True,
        "correlationId": "search-correlation",
        "details": "Success",
        "data": [{"id": "GB|abc", "companyName": "Acme"}],
    }
    assert requests[0].url.params["companyNumber"] == "123"
    assert requests[0].url.params["isoCode"] == "GB"
    assert "name" not in requests[0].url.params


def test_search_keeps_fields_the_spec_does_not_declare(settings: Settings) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": [{"id": "GB|abc", "newField": "kept"}]})

    result = call_tool(settings, handler, "search_companies", {"name": "Acme"})

    assert result.structured_content is not None
    assert result.structured_content["data"] == [{"id": "GB|abc", "newField": "kept"}]


def test_a_bad_iso_code_is_rejected(settings: Settings) -> None:
    result = call_tool(settings, empty, "search_companies", {"name": "Acme", "iso_code": "gbr"})

    assert result.is_error


def test_search_needs_a_name_or_a_company_number(settings: Settings) -> None:
    result = call_tool(settings, empty, "search_companies", {"name": "  "})

    assert result.is_error
    assert "Provide either `name` or `company_number`" in str(result.content)


def test_a_shape_that_does_not_fit_the_spec_is_answered_with_the_field_it_broke(
    settings: Settings,
) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": {"id": "GB|abc"}})

    result = call_tool(settings, handler, "search_companies", {"name": "Acme"})

    assert result.structured_content == {
        "success": False,
        "message": "Unexpected response: data: Input should be a valid array",
    }


def test_a_success_that_is_not_json_is_answered_as_a_failure(settings: Settings) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>maintenance</html>")

    result = call_tool(settings, handler, "search_companies", {"name": "Acme"})

    assert result.structured_content is not None
    assert result.structured_content["success"] is False


def test_a_timeout_is_answered_as_a_failure_without_a_status_code(settings: Settings) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    result = call_tool(settings, handler, "search_companies", {"name": "Acme"})

    assert result.is_error is False
    assert result.structured_content == {"success": False, "message": "timed out"}


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            400,
            {"correlationId": "error-correlation", "data": {"detail": "Invalid company"}},
            {
                "success": False,
                "statusCode": 400,
                "message": "Invalid company",
                "correlationId": "error-correlation",
            },
        ),
        (500, "boom", {"success": False, "statusCode": 500, "message": "boom"}),
    ],
)
def test_api_errors_are_answered_as_a_failed_reply(
    settings: Settings, status: int, body: object, expected: dict[str, object]
) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        if isinstance(body, str):
            return httpx2.Response(status, text=body)
        return httpx2.Response(status, json=body)

    result = call_tool(settings, handler, "search_companies", {"name": "Acme"})

    assert result.structured_content == expected
