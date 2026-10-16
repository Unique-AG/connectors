import json

import httpx2
import pytest

from kyckr_mcp.settings import Settings
from tests.support import call_tool


def test_an_order_that_finished_inlines_its_json_document_and_drops_the_links(
    settings: Settings,
) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(
                201,
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
        return httpx2.Response(200, json={"Data": {"companyName": "Acme", "documentNumber": "D-1"}})

    result = call_tool(
        settings, handler, "create_document_order", {"kyckr_id": "GB|abc", "product_id": "accounts"}
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


def test_an_order_sends_its_arguments_as_the_request_body(settings: Settings) -> None:
    configured = settings.model_copy(
        update={
            "kyckr_default_customer_reference": "ref-1",
            "kyckr_default_contact_email": "ops@example.com",
        }
    )
    bodies: list[object] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(201, json={"data": {"orderId": "9", "status": "Pending"}})

    result = call_tool(
        configured, handler, "create_document_order", {"kyckr_id": "GB|abc", "product_id": "p-1"}
    )

    assert bodies == [
        {
            "kyckrId": "GB|abc",
            "productId": "p-1",
            "customerReference": "ref-1",
            "contactEmail": "ops@example.com",
        }
    ]
    assert result.structured_content == {
        "success": True,
        "data": {"orderId": "9", "status": "Pending"},
    }


def test_an_order_reported_at_the_top_level_is_read_as_well(settings: Settings) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(201, json={"orderId": "9", "status": "Pending"})

    result = call_tool(
        settings, handler, "create_document_order", {"kyckr_id": "GB|abc", "product_id": "p-1"}
    )

    assert result.structured_content is not None
    assert result.structured_content["data"] == {"orderId": "9", "status": "Pending"}


@pytest.mark.parametrize("details", [{}, {"details": None}])
def test_an_order_without_upstream_details_has_no_details(
    settings: Settings, details: dict[str, object]
) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/download"):
            return httpx2.Response(200, json={"Data": {"companyName": "Acme"}})
        return httpx2.Response(200, json={**details, "data": {"orderId": 7, "status": "Success"}})

    result = call_tool(settings, handler, "get_order", {"order_id": 7})

    assert result.structured_content == {
        "success": True,
        "data": {"orderId": 7, "status": "Success", "documentJson": {"companyName": "Acme"}},
    }


def test_a_pdf_only_order_adds_the_notice_to_the_details(settings: Settings) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/download"):
            return httpx2.Response(404, json={"correlationId": "c", "data": {"detail": "none"}})
        return httpx2.Response(
            200, json={"details": "Success", "data": {"orderId": 7, "status": "Success"}}
        )

    result = call_tool(settings, handler, "get_order", {"order_id": "7"})

    content = result.structured_content
    assert content is not None
    assert str(content["details"]).startswith("Success ")
    assert "only available as a PDF" in str(content["details"])
    assert "documentJson" not in content["data"]


def test_an_order_that_is_still_pending_does_not_fetch_the_document(settings: Settings) -> None:
    paths: list[str] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        return httpx2.Response(200, json={"data": {"orderId": 7, "status": "Pending"}})

    call_tool(settings, handler, "get_order", {"order_id": "7"})

    assert not any(path.endswith("/download") for path in paths)


def test_list_orders_reads_a_page_and_drops_the_links_of_every_order(settings: Settings) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "data": {
                    "pageNumber": 1,
                    "totalCount": 2,
                    "orders": [
                        {"orderId": 1, "status": "Success", "links": {"document": "https://x"}},
                        {"orderId": 2, "status": "Pending"},
                    ],
                }
            },
        )

    result = call_tool(settings, handler, "list_orders", {})

    assert result.structured_content == {
        "success": True,
        "data": {
            "pageNumber": 1,
            "totalCount": 2,
            "orders": [{"orderId": 1, "status": "Success"}, {"orderId": 2, "status": "Pending"}],
        },
    }


def test_list_orders_also_reads_a_bare_array(settings: Settings) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": [{"orderId": 1, "links": {"data": "https://x"}}]})

    result = call_tool(settings, handler, "list_orders", {"iso_code": "gb"})

    assert result.structured_content == {"success": True, "data": [{"orderId": 1}]}


def download_answers(
    settings: Settings, download: httpx2.Response, order: dict[str, object] | None = None
) -> dict[str, object]:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/download"):
            return download
        return httpx2.Response(200, json={"data": order or {"orderId": 7, "status": "Success"}})

    result = call_tool(settings, handler, "get_order", {"order_id": "7"})
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.parametrize(
    "download",
    [
        httpx2.Response(200, content=b""),
        httpx2.Response(200, content=b"%PDF-1.7"),
        httpx2.Response(200, json=None),
        httpx2.Response(200, json={"Data": ["not", "an", "object"]}),
        httpx2.Response(200, json={}),
    ],
)
def test_a_finished_order_is_kept_when_its_download_has_no_json_document(
    settings: Settings, download: httpx2.Response
) -> None:
    reply = download_answers(settings, download)

    assert reply["success"] is True
    assert reply["data"] == {"orderId": 7, "status": "Success"}
    assert "only available as a PDF" in str(reply["details"])


def test_a_download_in_lower_case_data_is_read(settings: Settings) -> None:
    reply = download_answers(settings, httpx2.Response(200, json={"data": {"companyName": "Acme"}}))

    assert reply["data"] == {
        "orderId": 7,
        "status": "Success",
        "documentJson": {"companyName": "Acme"},
    }


RETRY_NOTE = "call `get_order` with its order id again"


def test_a_finished_order_is_kept_when_the_download_fails_with_a_server_error(
    settings: Settings,
) -> None:
    reply = download_answers(settings, httpx2.Response(503, text="busy"))

    assert reply["success"] is True
    assert reply["data"] == {"orderId": 7, "status": "Success"}
    assert RETRY_NOTE in str(reply["details"])
    assert "PDF" not in str(reply["details"])


def test_a_paid_order_is_not_lost_when_its_document_cannot_be_fetched(settings: Settings) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(201, json={"data": {"orderId": 55, "status": "Success"}})
        return httpx2.Response(429, text="slow down")

    result = call_tool(
        settings, handler, "create_document_order", {"kyckr_id": "GB|abc", "product_id": "p-1"}
    )

    content = result.structured_content
    assert content is not None
    assert content["success"] is True
    assert content["data"] == {"orderId": 55, "status": "Success"}
    assert RETRY_NOTE in str(content["details"])


def test_a_timeout_on_the_download_asks_to_try_again_and_does_not_call_the_document_pdf_only(
    settings: Settings,
) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/download"):
            raise httpx2.ReadTimeout("timed out", request=request)
        return httpx2.Response(200, json={"data": {"orderId": 7, "status": "Success"}})

    result = call_tool(settings, handler, "get_order", {"order_id": "7"})

    assert result.structured_content is not None
    assert RETRY_NOTE in str(result.structured_content["details"])
    assert "PDF" not in str(result.structured_content["details"])


def test_an_order_without_an_id_in_its_data_is_fetched_with_the_id_that_was_asked_for(
    settings: Settings,
) -> None:
    paths: list[str] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/download"):
            return httpx2.Response(200, json={"Data": {"companyName": "Acme"}})
        return httpx2.Response(200, json={"data": {"status": "Success"}})

    result = call_tool(settings, handler, "get_order", {"order_id": "7"})

    assert paths == ["/v2/orders/7", "/v2/orders/7/download"]
    assert result.structured_content == {
        "success": True,
        "data": {"status": "Success", "documentJson": {"companyName": "Acme"}},
    }


def test_a_failed_order_does_not_fetch_a_document(settings: Settings) -> None:
    paths: list[str] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        return httpx2.Response(200, json={"data": {"orderId": 7, "status": "Failed"}})

    result = call_tool(settings, handler, "get_order", {"order_id": "7"})

    assert result.structured_content == {
        "success": True,
        "data": {"orderId": 7, "status": "Failed"},
    }
    assert paths == ["/v2/orders/7"]


def test_a_created_order_with_nothing_in_it_has_no_data(settings: Settings) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(201, json={"correlationId": "c-1"})

    result = call_tool(
        settings, handler, "create_document_order", {"kyckr_id": "GB|abc", "product_id": "p-1"}
    )

    assert result.structured_content == {"success": True, "correlationId": "c-1"}


def test_a_success_in_the_kyckr_body_does_not_crash_the_reply(settings: Settings) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"success": "yes", "data": [{"id": "GB|abc"}]})

    result = call_tool(settings, handler, "search_companies", {"name": "Acme"})

    assert result.structured_content == {"success": True, "data": [{"id": "GB|abc"}]}
