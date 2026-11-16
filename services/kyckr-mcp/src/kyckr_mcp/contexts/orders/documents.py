from typing import cast

from pydantic import ValidationError

from kyckr_mcp.contexts.orders.models import OrderData
from kyckr_mcp.contexts.orders.models import OrderResult
from kyckr_mcp.upstream import BaseResponse
from kyckr_mcp.upstream import GET_ORDERS_ORDER_ID_DOWNLOAD
from kyckr_mcp.upstream import GetOrdersOrderIdDownloadPath
from kyckr_mcp.upstream import GetOrdersOrderIdDownloadQuery
from kyckr_mcp.upstream import GetOrdersOrderIdDownloadRequest
from kyckr_mcp.upstream import OrderDetails
from kyckr_mcp.upstream import PostOrdersResponse
from kyckr_mcp.upstream import Upstream
from kyckr_mcp.upstream import UpstreamError

_PDF_NOT_SUPPORTED_DETAIL = (
    "This document is only available as a PDF. PDF delivery is not yet supported; "
    "support is coming soon."
)
_DOCUMENT_NOT_FETCHED_DETAIL = (
    "The document could not be fetched just now. The order is placed: call `get_order` with "
    "its order id again to get the document."
)


def as_order(details: OrderDetails | None) -> OrderData | None:
    """The order without its download links."""
    if details is None:
        return None
    return OrderData.model_validate(details.model_dump(by_alias=True, exclude={"links"}))


def created_order(response: PostOrdersResponse) -> OrderData | None:
    if response.data is not None:
        return as_order(response.data)
    if response.status is None and response.order_id is None:
        return None
    return OrderData.model_validate({"orderId": response.order_id, "status": response.status})


async def order_result(
    *,
    upstream: Upstream,
    response: BaseResponse,
    order: OrderData | None,
    order_id: str | None = None,
) -> OrderResult:
    """The order, with its JSON document once it finished. `order_id` stands in for a missing
    orderId.
    """
    notice = None
    if order is not None and order.status == "Success":
        finished_id = str(order.order_id) if order.order_id is not None else order_id
        if finished_id is not None:
            document, notice = await _document(upstream, finished_id)
            order = order.model_copy(update={"document_json": document})
    fields = response.model_dump(by_alias=True, exclude={"data"})
    details = " ".join(part for part in (fields.get("details"), notice) if part)
    return OrderResult.model_validate({**fields, "details": details or None, "data": order})


async def _document(
    upstream: Upstream, order_id: str
) -> tuple[dict[str, object] | None, str | None]:
    try:
        download = await upstream.call(
            GET_ORDERS_ORDER_ID_DOWNLOAD,
            GetOrdersOrderIdDownloadRequest(
                path=GetOrdersOrderIdDownloadPath(order_id=order_id),
                query=GetOrdersOrderIdDownloadQuery(format="json"),
            ),
        )
    except UpstreamError as error:
        no_json_view = error.status_code == 404 or isinstance(error.__cause__, ValidationError)
        return None, _PDF_NOT_SUPPORTED_DETAIL if no_json_view else _DOCUMENT_NOT_FETCHED_DETAIL
    body = download.model_dump(by_alias=True)
    document = body.get("Data", body.get("data"))
    if isinstance(document, dict):
        return cast(dict[str, object], document), None
    return None, _PDF_NOT_SUPPORTED_DETAIL
