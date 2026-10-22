from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

from kyckr_mcp.models.vendor_responses import (
    BaseResponse,
    GetCompaniesKyckrIdDocumentsResponse,
    GetCompaniesKyckrIdEnhancedResponse,
    GetCompaniesKyckrIdResponse,
    GetCompaniesResponse,
    GetOrderResponse,
    OrderDetails,
)


def _without_none(value: object) -> object:
    if isinstance(value, dict):
        return {key: _without_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    return value


class Reply(BaseModel):
    """What every tool answers with, next to what Kyckr returned. Empty fields are left out."""

    success: bool
    statusCode: int | None = None
    message: str | None = None

    @model_serializer(mode="wrap")
    def _omit_empty_fields(self, handler: SerializerFunctionWrapHandler):  # noqa: ANN202
        # No return annotation: one would replace the output schema FastMCP publishes.
        return _without_none(handler(self))


class OrderData(OrderDetails):
    documentJson: dict[str, object] | None = Field(
        None,
        description=(
            "Structured view of the ordered document, added once `status` is `Success`. Field "
            "names are PascalCase (Kyckr download-endpoint convention). Absent while `status` is "
            "`Pending` or `Failed`, and when the registry has no JSON view of the filing, in "
            "which case `details` says the document is PDF-only."
        ),
    )


def answer[R: Reply](reply: type[R], response: BaseModel) -> R:
    """A successful reply of the given type, made from what Kyckr returned."""
    return reply.model_validate({**response.model_dump(), "success": True})


class SearchCompaniesReply(Reply, GetCompaniesResponse): ...


class LiteProfileReply(Reply, GetCompaniesKyckrIdResponse): ...


class EnhancedProfileReply(Reply, GetCompaniesKyckrIdEnhancedResponse): ...


class CompanyDocumentsReply(Reply, GetCompaniesKyckrIdDocumentsResponse): ...


class ListOrdersReply(Reply, GetOrderResponse): ...


class OrderReply(Reply, BaseResponse):
    data: OrderData | None = None
