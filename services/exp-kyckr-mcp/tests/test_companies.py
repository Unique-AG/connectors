import httpx2
import pytest

from kyckr_mcp.settings import Settings
from tests.support import call_tool


def recording(requests: list[httpx2.Request], body: object, status: int = 200):  # noqa: ANN201
    async def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(status, json=body)

    return handler


def test_the_enhanced_profile_is_fetched_from_its_own_endpoint_with_the_customer_reference(
    settings: Settings,
) -> None:
    configured = settings.model_copy(update={"kyckr_default_customer_reference": "ref-1"})
    requests: list[httpx2.Request] = []
    body = {"data": {"activities": [{"code": "63120"}]}}

    result = call_tool(
        configured, recording(requests, body), "get_enhanced_profile", {"kyckr_id": "GB|abc"}
    )

    assert requests[0].url.raw_path.startswith(b"/v2/companies/GB%7Cabc/enhanced?")
    assert requests[0].url.params["customerReference"] == "ref-1"
    assert result.structured_content == {
        "success": True,
        "data": {"activities": [{"code": "63120"}]},
    }


def test_a_pending_enhanced_profile_is_answered_with_the_order_to_poll(settings: Settings) -> None:
    body = {"data": {"status": "Pending", "orderId": 12345, "cost": {"type": "credit", "value": 1}}}

    result = call_tool(
        settings, recording([], body, status=202), "get_enhanced_profile", {"kyckr_id": "GB|abc"}
    )

    assert result.structured_content == {
        "success": True,
        "data": {"status": "Pending", "orderId": 12345, "cost": {"type": "credit", "value": 1}},
    }


def test_an_enhanced_profile_that_is_not_available_is_answered_with_its_status_code(
    settings: Settings,
) -> None:
    body = {"correlationId": "c-405", "data": {"detail": "Not available for this jurisdiction"}}

    result = call_tool(
        settings, recording([], body, status=405), "get_enhanced_profile", {"kyckr_id": "XX|abc"}
    )

    assert result.structured_content == {
        "success": False,
        "statusCode": 405,
        "message": "Not available for this jurisdiction",
        "correlationId": "c-405",
    }


def test_the_document_list_passes_the_continuation_key_and_hands_back_the_next_one(
    settings: Settings,
) -> None:
    requests: list[httpx2.Request] = []
    body = {
        "data": [{"id": "p-1", "name": "Accounts", "cost": {"value": 3}}],
        "continuationKey": "k2",
    }

    result = call_tool(
        settings,
        recording(requests, body),
        "list_company_documents",
        {"kyckr_id": "GB|abc", "continuation_key": " k1 "},
    )

    assert requests[0].url.params["continuationKey"] == "k1"
    assert result.structured_content == {
        "success": True,
        "data": [{"id": "p-1", "name": "Accounts", "cost": {"value": 3}}],
        "continuationKey": "k2",
    }


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
def test_arguments_are_trimmed_and_blank_ones_are_not_sent(
    settings: Settings, tool: str, arguments: dict[str, object], query: dict[str, str]
) -> None:
    requests: list[httpx2.Request] = []

    call_tool(settings, recording(requests, {"data": []}), tool, arguments)

    assert dict(requests[0].url.params) == query


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_lite_profile", {"kyckr_id": "  "}),
        ("get_enhanced_profile", {"kyckr_id": ""}),
        ("create_document_order", {"kyckr_id": "GB|a", "product_id": " "}),
        ("get_order", {"order_id": " "}),
    ],
)
def test_a_blank_id_is_rejected_before_any_request_is_made(
    settings: Settings, tool: str, arguments: dict[str, object]
) -> None:
    requests: list[httpx2.Request] = []

    result = call_tool(settings, recording(requests, {}), tool, arguments)

    assert result.is_error
    assert requests == []


@pytest.mark.parametrize(
    "data", [{"representatives": "oops"}, {"status": "Active"}, {"companyName": 1}]
)
def test_an_enhanced_profile_that_does_not_fit_the_spec_is_answered_with_the_field_it_broke(
    settings: Settings, data: dict[str, object]
) -> None:
    result = call_tool(
        settings, recording([], {"data": data}), "get_enhanced_profile", {"kyckr_id": "GB|abc"}
    )

    content = result.structured_content
    assert content is not None
    assert content["success"] is False
    assert str(content["message"]).startswith("Unexpected response: data")


def test_a_sparse_enhanced_profile_is_a_profile_and_not_a_pending_order(settings: Settings) -> None:
    data = {"companyName": "Acme", "cost": {"type": "credit", "value": 3}}

    result = call_tool(
        settings, recording([], {"data": data}), "get_enhanced_profile", {"kyckr_id": "GB|abc"}
    )

    assert result.structured_content == {"success": True, "data": data}
