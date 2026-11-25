from typing import cast

from pydantic import ValidationError

from kyckr_mcp.contexts.orders.models import OrderReply
from kyckr_mcp.upstream import GET_ORDERS_ORDER_ID_DOWNLOAD
from kyckr_mcp.upstream import GetOrdersOrderIdDownloadPath
from kyckr_mcp.upstream import GetOrdersOrderIdDownloadQuery
from kyckr_mcp.upstream import GetOrdersOrderIdDownloadRequest
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


async def with_document(
    *, upstream: Upstream, reply: OrderReply, order_id: str | None = None
) -> OrderReply:
    """The order, with its JSON document once it finished. `order_id` stands in for a missing
    orderId.
    """
    order = reply.data
    if order is None or order.status != "Success":
        return reply
    finished_id = str(order.order_id) if order.order_id is not None else order_id
    if finished_id is None:
        return reply
    document, notice = await _document(upstream, finished_id)
    details = " ".join(part for part in (reply.details, notice) if part)
    return reply.model_copy(
        update={
            "details": details or None,
            "data": order.model_copy(update={"document_json": document}),
        }
    )


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
