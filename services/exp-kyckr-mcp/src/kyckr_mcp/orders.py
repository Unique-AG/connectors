from mcp_openapi.upstream import Operation, OperationClient, UpstreamError
from pydantic import TypeAdapter, ValidationError

from kyckr_mcp.client import KyckrApiError
from kyckr_mcp.models.replies import OrderData, OrderReply
from kyckr_mcp.models.vendor_responses import BaseResponse, OrderDetails, PostOrdersResponse

_PDF_NOT_SUPPORTED_DETAIL = (
    "This document is only available as a PDF. PDF delivery is not yet supported; "
    "support is coming soon."
)
_DOCUMENT_NOT_FETCHED_DETAIL = (
    "The document could not be fetched just now. The order is placed: call `get_order` with "
    "its order id again to get the document."
)
DOWNLOAD_ORDER = Operation("get-orders-orderId-download", TypeAdapter(dict[str, object]))


def as_order(details: OrderDetails | None) -> OrderData | None:
    """The order without its download links."""
    if details is None:
        return None
    fields = details.model_dump()
    fields.pop("links", None)
    return OrderData.model_validate(fields)


def created_order(response: PostOrdersResponse) -> OrderData | None:
    if response.data is not None:
        return as_order(response.data)
    if response.status is None and response.orderId is None:
        return None
    return OrderData.model_validate({"orderId": response.orderId, "status": response.status})


async def _document(
    api: OperationClient, order_id: str
) -> tuple[dict[str, object] | None, str | None]:
    try:
        body = await api.call(DOWNLOAD_ORDER, orderId=order_id, format="json")
    except UpstreamError as error:
        unreadable = isinstance(error.__cause__, ValidationError)
        return None, _PDF_NOT_SUPPORTED_DETAIL if unreadable else _DOCUMENT_NOT_FETCHED_DETAIL
    except KyckrApiError as error:
        no_json_view = error.status == 404
        return None, _PDF_NOT_SUPPORTED_DETAIL if no_json_view else _DOCUMENT_NOT_FETCHED_DETAIL
    document = body.get("Data", body.get("data"))
    if isinstance(document, dict):
        return {str(key): value for key, value in document.items()}, None
    return None, _PDF_NOT_SUPPORTED_DETAIL


def finished_id(order: OrderData | None, default: str | None = None) -> str | None:
    """The id of an order that finished, or None. `default` stands in for a missing orderId."""
    if order is None or order.status != "Success":
        return None
    return str(order.orderId) if order.orderId is not None else default


async def order_reply(
    api: OperationClient,
    response: BaseResponse,
    order: OrderData | None,
    finished_order_id: str | None,
) -> OrderReply:
    """A reply for an order, with the JSON document of `finished_order_id` added to it."""
    notice = None
    if order is not None and finished_order_id is not None:
        document, notice = await _document(api, finished_order_id)
        order = order.model_copy(update={"documentJson": document})
    fields = response.model_dump(exclude={"data"})
    details = " ".join(part for part in (fields.get("details"), notice) if part)
    return OrderReply.model_validate(
        {**fields, "success": True, "details": details or None, "data": order}
    )
