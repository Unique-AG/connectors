import pytest

from tests.conftest import CallTool
from tests.conftest import CallToolWith
from tests.conftest import FakeKyckr
from tests.conftest import structured


async def test_the_enhanced_profile_is_fetched_from_its_own_endpoint(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"data": {"activities": [{"code": "63120"}]}})

    result = await call_tool("get_enhanced_profile", {"kyckr_id": "GB|abc"})

    assert kyckr.requests[0].url.raw_path.startswith(b"/v2/companies/GB%7Cabc/enhanced")
    assert result.structured_content == {
        "success": True,
        "data": {"activities": [{"code": "63120"}]},
    }


async def test_a_pending_enhanced_profile_is_answered_with_the_order_to_poll(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    data = {"status": "Pending", "orderId": 12345, "cost": {"type": "credit", "value": 1}}
    kyckr.answers({"data": data}, status=202)

    result = await call_tool("get_enhanced_profile", {"kyckr_id": "GB|abc"})

    assert result.structured_content == {"success": True, "data": data}


async def test_an_enhanced_profile_that_is_not_available_is_answered_with_its_status_code(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers(
        {"correlationId": "c-405", "data": {"detail": "Not available for this jurisdiction"}},
        status=405,
    )

    result = await call_tool("get_enhanced_profile", {"kyckr_id": "XX|abc"})

    assert result.structured_content == {
        "success": False,
        "statusCode": 405,
        "message": "Not available for this jurisdiction",
        "correlationId": "c-405",
    }


async def test_the_document_list_passes_the_continuation_key_and_hands_back_the_next_one(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    body = {
        "data": [{"id": "p-1", "name": "Accounts", "cost": {"value": 3}}],
        "continuationKey": "k2",
    }
    kyckr.answers(body)

    result = await call_tool(
        "list_company_documents", {"kyckr_id": "GB|abc", "continuation_key": " k1 "}
    )

    assert kyckr.requests[0].url.params["continuationKey"] == "k1"
    assert result.structured_content == {"success": True, **body}


@pytest.mark.parametrize(
    ("tool", "arguments", "query"),
    [
        ("search_companies", {"name": "Acme", "iso_code": " "}, {"name": "Acme"}),
        (
            "search_companies",
            {"name": "Acme", "iso_code": " gb "},
            {"name": "Acme", "isoCode": "GB"},
        ),
        ("list_company_documents", {"kyckr_id": "GB|a", "continuation_key": " "}, {}),
        (
            "list_orders",
            {"start_date": "2026-01-01", "end_date": " 2026-02-01 ", "iso_code": "ie"},
            {"startDate": "2026-01-01", "endDate": "2026-02-01", "isoCode": "IE"},
        ),
    ],
)
async def test_arguments_are_trimmed_and_blank_ones_are_not_sent(
    call_tool: CallTool,
    kyckr: FakeKyckr,
    *,
    tool: str,
    arguments: dict[str, object],
    query: dict[str, str],
) -> None:
    kyckr.answers({"data": []})

    await call_tool(tool, arguments)

    assert dict(kyckr.requests[0].url.params) == query


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_lite_profile", {"kyckr_id": "  "}),
        ("get_enhanced_profile", {"kyckr_id": ""}),
        ("create_document_order", {"kyckr_id": "GB|a", "product_id": " "}),
        ("get_order", {"order_id": " "}),
    ],
)
async def test_a_blank_id_is_rejected_before_any_request_is_made(
    call_tool: CallTool, kyckr: FakeKyckr, *, tool: str, arguments: dict[str, object]
) -> None:
    kyckr.answers({})

    result = await call_tool(tool, arguments)

    assert result.is_error
    assert kyckr.requests == []


async def test_a_pending_order_status_in_an_enhanced_profile_is_answered_with_the_field_it_broke(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"data": {"status": "Active"}})

    result = await call_tool("get_enhanced_profile", {"kyckr_id": "GB|abc"})

    content = structured(result)
    assert content["success"] is False
    assert "data" in str(content["message"])
    assert "statusCode" not in content


async def test_a_sparse_enhanced_profile_is_a_profile_and_not_a_pending_order(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    data = {"companyName": "Acme", "cost": {"type": "credit", "value": 3}}
    kyckr.answers({"data": data})

    result = await call_tool("get_enhanced_profile", {"kyckr_id": "GB|abc"})

    assert result.structured_content == {"success": True, "data": data}


@pytest.mark.parametrize(
    ("tool", "body"),
    [
        ("get_lite_profile", {"data": {"companyName": "Acme"}}),
        ("get_enhanced_profile", {"data": {"companyName": "Acme"}}),
        ("list_company_documents", {"data": []}),
    ],
)
async def test_a_company_call_sends_the_configured_customer_reference(
    call_tool_with: CallToolWith, kyckr: FakeKyckr, *, tool: str, body: dict[str, object]
) -> None:
    call_tool = call_tool_with(default_customer_reference="ref-1")
    kyckr.answers(body)

    result = await call_tool(tool, {"kyckr_id": "GB|abc"})

    assert kyckr.requests[0].url.params["customerReference"] == "ref-1"
    assert structured(result) == {"success": True, **body}
