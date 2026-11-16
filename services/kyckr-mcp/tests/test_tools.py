from typing import cast

from fastmcp import Client
from fastmcp import FastMCP
import httpx2
from mcp.types import Tool
import pytest

from tests.conftest import CallTool
from tests.conftest import FakeKyckr
from tests.conftest import structured

ARGUMENTS: dict[str, dict[str, object]] = {
    "search_companies": {"name": "Acme"},
    "get_lite_profile": {"kyckr_id": "GB|abc"},
    "get_enhanced_profile": {"kyckr_id": "GB|abc"},
    "list_company_documents": {"kyckr_id": "GB|abc"},
    "create_document_order": {"kyckr_id": "GB|abc", "product_id": "p-1"},
    "get_order": {"order_id": "7"},
    "list_orders": {},
}


async def list_tools(server: FastMCP) -> dict[str, Tool]:
    async with Client(server) as client:
        return {tool.name: tool for tool in await client.list_tools()}


async def test_every_tool_has_a_title_an_icon_and_a_system_prompt(server: FastMCP) -> None:
    for name, tool in (await list_tools(server)).items():
        assert tool.title, name
        assert tool.annotations
        assert tool.annotations.title == tool.title, name
        assert tool.meta
        assert tool.meta["unique.app/icon"], name
        assert tool.meta["unique.app/system-prompt"], name


async def test_system_prompts_use_the_argument_names_the_tools_take(server: FastMCP) -> None:
    for name, tool in (await list_tools(server)).items():
        meta = cast(dict[str, object], tool.meta)
        prompt = str(meta["unique.app/system-prompt"]).replace("data.orderId", "")
        for camel in ("kyckrId", "isoCode", "orderId", "productId"):
            assert camel not in prompt, (name, camel)


async def test_a_server_can_run_two_sessions_one_after_the_other(server: FastMCP) -> None:
    counts: list[int] = []
    for _ in range(2):
        async with Client(server) as client:
            counts.append(len(await client.list_tools()))

    assert counts[0] == counts[1] == len(ARGUMENTS)


async def test_search_sends_the_arguments_kyckr_expects_and_answers_without_empty_fields(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    body = {
        "correlationId": "search-correlation",
        "details": "Success",
        "data": [{"id": "GB|abc", "companyName": "Acme"}],
    }
    kyckr.answers(body)

    result = await call_tool("search_companies", {"company_number": " 123 ", "iso_code": "gb"})

    params = kyckr.requests[0].url.params
    assert structured(result) == {"success": True, **body}
    assert params["companyNumber"] == "123"
    assert params["isoCode"] == "GB"
    assert "name" not in params


async def test_search_keeps_fields_the_spec_does_not_declare(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"data": [{"id": "GB|abc", "newField": "kept"}]})

    result = await call_tool("search_companies", {"name": "Acme"})

    assert structured(result)["data"] == [{"id": "GB|abc", "newField": "kept"}]


async def test_a_bad_iso_code_is_rejected(call_tool: CallTool, kyckr: FakeKyckr) -> None:
    kyckr.answers({"data": []})

    result = await call_tool("search_companies", {"name": "Acme", "iso_code": "gbr"})

    assert result.is_error
    assert kyckr.requests == []


async def test_search_needs_a_name_or_a_company_number(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    result = await call_tool("search_companies", {"name": "  "})

    assert result.is_error
    assert "Provide either `name` or `company_number`" in str(result.content)
    assert kyckr.requests == []


async def test_a_shape_that_does_not_fit_the_spec_is_answered_with_the_field_it_broke(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"data": {"id": "GB|abc"}})

    result = await call_tool("search_companies", {"name": "Acme"})

    content = structured(result)
    assert content["success"] is False
    assert "data" in str(content["message"])
    assert "statusCode" not in content


async def test_a_success_that_is_not_json_is_answered_as_a_failure(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.handler = lambda _: httpx2.Response(200, text="<html>maintenance</html>")

    result = await call_tool("search_companies", {"name": "Acme"})

    assert structured(result)["success"] is False


async def test_a_timeout_is_answered_as_a_failure_without_a_status_code(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    kyckr.handler = handler

    result = await call_tool("search_companies", {"name": "Acme"})

    assert result.is_error is False
    assert structured(result) == {"success": False, "message": "timed out"}


@pytest.mark.parametrize("tool", list(ARGUMENTS))
async def test_every_tool_answers_a_kyckr_error_as_a_failed_reply(
    call_tool: CallTool, kyckr: FakeKyckr, tool: str
) -> None:
    kyckr.answers({"correlationId": "c-410", "data": {"detail": "Gone"}}, status=410)

    result = await call_tool(tool, ARGUMENTS[tool])

    assert not result.is_error
    assert structured(result) == {
        "success": False,
        "statusCode": 410,
        "message": "Gone",
        "correlationId": "c-410",
    }


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx2.Response(404, json={"title": "Not found"}), "Not found"),
        (httpx2.Response(500, text="boom"), "boom"),
        (httpx2.Response(502), "HTTP 502"),
        (httpx2.Response(500, text="x" * 300), f"{'x' * 200}..."),
    ],
)
async def test_an_error_without_a_kyckr_detail_is_answered_with_what_it_has(
    call_tool: CallTool, kyckr: FakeKyckr, *, response: httpx2.Response, message: str
) -> None:
    kyckr.handler = lambda _: response

    result = await call_tool("search_companies", {"name": "Acme"})

    assert structured(result) == {
        "success": False,
        "statusCode": response.status_code,
        "message": message,
    }


async def test_a_turned_away_request_is_retried(call_tool: CallTool, kyckr: FakeKyckr) -> None:
    answers = iter([httpx2.Response(429), httpx2.Response(200, json={"data": [{"id": "GB|abc"}]})])
    kyckr.handler = lambda _: next(answers)

    result = await call_tool("search_companies", {"name": "Acme"})

    assert structured(result) == {"success": True, "data": [{"id": "GB|abc"}]}
    assert len(kyckr.requests) == 2


async def test_a_rate_limit_that_outlasts_the_retries_keeps_kyckrs_message(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"correlationId": "c-429", "data": {"detail": "Rate limit"}}, status=429)

    result = await call_tool("search_companies", {"name": "Acme"})

    assert structured(result) == {
        "success": False,
        "statusCode": 429,
        "message": "Rate limit",
        "correlationId": "c-429",
    }
    assert len(kyckr.requests) == 3


async def test_a_paid_read_is_not_sent_again_on_a_503(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"correlationId": "c-503", "data": {"detail": "busy"}}, status=503)

    result = await call_tool("get_lite_profile", {"kyckr_id": "GB|abc"})

    assert structured(result) == {
        "success": False,
        "statusCode": 503,
        "message": "busy",
        "correlationId": "c-503",
    }
    assert len(kyckr.requests) == 1


async def test_a_success_field_in_kyckrs_body_does_not_override_the_reply(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"success": "nope", "data": [{"id": "GB|abc"}]})

    result = await call_tool("search_companies", {"name": "Acme"})

    assert structured(result) == {"success": True, "data": [{"id": "GB|abc"}]}
