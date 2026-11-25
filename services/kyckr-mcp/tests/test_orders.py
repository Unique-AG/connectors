from collections.abc import Callable
import json

import httpx2
import pytest

from tests.conftest import CallTool
from tests.conftest import CallToolWith
from tests.conftest import FakeKyckr
from tests.conftest import structured

ORDER: dict[str, object] = {"kyckr_id": "GB|abc", "product_id": "p-1"}
RETRY_NOTE = "call `get_order` with its order id again"


def is_download(request: httpx2.Request) -> bool:
    return request.url.path.endswith("/download")


async def test_an_order_that_finished_inlines_its_json_document_and_drops_the_links(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            data = {"orderId": 123, "status": "Success", "links": {"document": "https://x.test"}}
            return httpx2.Response(
                201, json={"correlationId": "c-1", "details": "Success", "data": data}
            )
        return httpx2.Response(200, json={"Data": {"companyName": "Acme", "documentNumber": "D-1"}})

    kyckr.handler = handler

    result = await call_tool("create_document_order", {"kyckr_id": "GB|abc", "product_id": "a"})

    assert structured(result) == {
        "correlationId": "c-1",
        "details": "Success",
        "data": {
            "orderId": 123,
            "status": "Success",
            "documentJson": {"companyName": "Acme", "documentNumber": "D-1"},
        },
    }


async def test_an_order_sends_its_arguments_and_the_configured_defaults_as_the_body(
    call_tool_with: CallToolWith, kyckr: FakeKyckr
) -> None:
    call_tool = call_tool_with(
        default_customer_reference="ref-1", default_contact_email="ops@example.com"
    )
    kyckr.answers({"data": {"orderId": "9", "status": "Pending"}}, status=201)

    result = await call_tool("create_document_order", ORDER)

    assert json.loads(kyckr.requests[0].content) == {
        "kyckrId": "GB|abc",
        "productId": "p-1",
        "customerReference": "ref-1",
        "contactEmail": "ops@example.com",
    }
    assert structured(result) == {"data": {"orderId": "9", "status": "Pending"}}


async def test_an_order_leaves_out_the_defaults_nobody_configured(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"data": {"orderId": "9", "status": "Pending"}}, status=201)

    await call_tool("create_document_order", ORDER)

    assert json.loads(kyckr.requests[0].content) == {"kyckrId": "GB|abc", "productId": "p-1"}


async def test_an_order_reported_at_the_top_level_is_read_as_well(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"orderId": "9", "status": "Pending"}, status=201)

    result = await call_tool("create_document_order", ORDER)

    assert structured(result)["data"] == {"orderId": "9", "status": "Pending"}


@pytest.mark.parametrize(
    ("data", "expected_id"),
    [
        ({"status": "Success"}, "123"),
        ({"orderId": "9", "status": "Success"}, "9"),
    ],
)
async def test_the_envelope_order_id_only_fills_in_a_missing_one(
    call_tool: CallTool, kyckr: FakeKyckr, *, data: dict[str, object], expected_id: str
) -> None:
    kyckr.handler = lambda request: (
        httpx2.Response(200, json={"Data": {"companyName": "Acme"}})
        if is_download(request)
        else httpx2.Response(201, json={"orderId": "123", "data": data})
    )

    result = await call_tool("create_document_order", ORDER)

    assert kyckr.requests[-1].url.path == f"/v2/orders/{expected_id}/download"
    assert structured(result)["data"] == {
        "orderId": expected_id,
        "status": "Success",
        "documentJson": {"companyName": "Acme"},
    }


async def test_an_empty_order_id_in_the_data_is_not_replaced_by_the_envelope_one(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"orderId": "123", "data": {"orderId": "", "status": "Success"}}, status=201)

    await call_tool("create_document_order", ORDER)

    assert [request.url.path for request in kyckr.requests] == ["/v2/orders"]


async def test_the_envelope_status_fills_in_a_missing_one(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.handler = lambda request: (
        httpx2.Response(200, json={"Data": {"companyName": "Acme"}})
        if is_download(request)
        else httpx2.Response(201, json={"status": "Success", "data": {"orderId": "9"}})
    )

    result = await call_tool("create_document_order", ORDER)

    assert structured(result)["data"] == {
        "orderId": "9",
        "status": "Success",
        "documentJson": {"companyName": "Acme"},
    }


@pytest.mark.parametrize("details", [{}, {"details": None}])
async def test_an_order_without_upstream_details_has_no_details(
    call_tool: CallTool, kyckr: FakeKyckr, details: dict[str, object]
) -> None:
    kyckr.handler = lambda request: (
        httpx2.Response(200, json={"Data": {"companyName": "Acme"}})
        if is_download(request)
        else httpx2.Response(200, json={**details, "data": {"orderId": 7, "status": "Success"}})
    )

    result = await call_tool("get_order", {"order_id": 7})

    assert structured(result) == {
        "data": {"orderId": 7, "status": "Success", "documentJson": {"companyName": "Acme"}},
    }


async def test_a_pdf_only_order_adds_the_notice_to_the_details(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.handler = lambda request: (
        httpx2.Response(404, json={"correlationId": "c", "data": {"detail": "none"}})
        if is_download(request)
        else httpx2.Response(
            200, json={"details": "Success", "data": {"orderId": 7, "status": "Success"}}
        )
    )

    result = await call_tool("get_order", {"order_id": "7"})

    content = structured(result)
    details = content["details"]
    assert isinstance(details, str)
    assert details.startswith("Success ")
    assert "only available as a PDF" in details
    assert content["data"] == {"orderId": 7, "status": "Success"}


@pytest.mark.parametrize("status", ["Pending", "Failed"])
async def test_an_order_that_did_not_finish_does_not_fetch_a_document(
    call_tool: CallTool, kyckr: FakeKyckr, status: str
) -> None:
    kyckr.answers({"data": {"orderId": 7, "status": status}})

    result = await call_tool("get_order", {"order_id": "7"})

    assert structured(result) == {"data": {"orderId": 7, "status": status}}
    assert [request.url.path for request in kyckr.requests] == ["/v2/orders/7"]


async def test_list_orders_reads_a_page_and_drops_the_links_of_every_order(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers(
        {
            "data": {
                "pageNumber": 1,
                "totalCount": 2,
                "orders": [
                    {"orderId": 1, "status": "Success", "links": {"document": "https://x.test"}},
                    {"orderId": 2, "status": "Pending"},
                ],
            }
        }
    )

    result = await call_tool("list_orders", {})

    assert structured(result) == {
        "data": {
            "pageNumber": 1,
            "totalCount": 2,
            "orders": [{"orderId": 1, "status": "Success"}, {"orderId": 2, "status": "Pending"}],
        },
    }


async def test_list_orders_also_reads_a_bare_array(call_tool: CallTool, kyckr: FakeKyckr) -> None:
    kyckr.answers({"data": [{"orderId": 1, "links": {"data": "https://x.test"}}]})

    result = await call_tool("list_orders", {"iso_code": "gb"})

    assert structured(result) == {"data": [{"orderId": 1}]}


async def finished_order_with_download(
    call_tool: CallTool, kyckr: FakeKyckr, download: httpx2.Response
) -> dict[str, object]:
    kyckr.handler = lambda request: (
        download
        if is_download(request)
        else httpx2.Response(200, json={"data": {"orderId": 7, "status": "Success"}})
    )
    return structured(await call_tool("get_order", {"order_id": "7"}))


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
async def test_a_finished_order_is_kept_when_its_download_has_no_json_document(
    call_tool: CallTool, kyckr: FakeKyckr, download: httpx2.Response
) -> None:
    reply = await finished_order_with_download(call_tool, kyckr, download)

    details = reply["details"]
    assert isinstance(details, str)
    assert reply["data"] == {"orderId": 7, "status": "Success"}
    assert "only available as a PDF" in details


async def test_a_download_in_lower_case_data_is_read(call_tool: CallTool, kyckr: FakeKyckr) -> None:
    download = httpx2.Response(200, json={"data": {"companyName": "Acme"}})

    reply = await finished_order_with_download(call_tool, kyckr, download)

    assert reply["data"] == {
        "orderId": 7,
        "status": "Success",
        "documentJson": {"companyName": "Acme"},
    }


def download_unavailable(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(503, text="busy")


def download_timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("timed out", request=request)


@pytest.mark.parametrize("download", [download_unavailable, download_timeout])
async def test_a_finished_order_is_kept_and_asks_to_try_again_when_its_download_fails(
    call_tool: CallTool,
    kyckr: FakeKyckr,
    download: Callable[[httpx2.Request], httpx2.Response],
) -> None:
    kyckr.handler = lambda request: (
        download(request)
        if is_download(request)
        else httpx2.Response(200, json={"data": {"orderId": 7, "status": "Success"}})
    )

    reply = structured(await call_tool("get_order", {"order_id": "7"}))

    details = reply["details"]
    assert isinstance(details, str)
    assert reply["data"] == {"orderId": 7, "status": "Success"}
    assert RETRY_NOTE in details
    assert "PDF" not in details


async def test_a_paid_order_is_not_lost_when_its_document_cannot_be_fetched(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.handler = lambda request: (
        httpx2.Response(201, json={"data": {"orderId": 55, "status": "Success"}})
        if request.method == "POST"
        else httpx2.Response(429, text="slow down")
    )

    content = structured(await call_tool("create_document_order", ORDER))

    details = content["details"]
    assert isinstance(details, str)
    assert content["data"] == {"orderId": 55, "status": "Success"}
    assert RETRY_NOTE in details


async def test_an_order_without_an_id_in_its_data_is_fetched_with_the_id_that_was_asked_for(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.handler = lambda request: (
        httpx2.Response(200, json={"Data": {"companyName": "Acme"}})
        if is_download(request)
        else httpx2.Response(200, json={"data": {"status": "Success"}})
    )

    result = await call_tool("get_order", {"order_id": "7"})

    assert [request.url.path for request in kyckr.requests] == [
        "/v2/orders/7",
        "/v2/orders/7/download",
    ]
    assert structured(result) == {
        "data": {"status": "Success", "documentJson": {"companyName": "Acme"}},
    }


async def test_a_created_order_with_nothing_in_it_has_no_data(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"correlationId": "c-1"}, status=201)

    result = await call_tool("create_document_order", ORDER)

    assert structured(result) == {"correlationId": "c-1"}
