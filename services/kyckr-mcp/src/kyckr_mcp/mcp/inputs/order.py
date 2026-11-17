from typing import Annotated

from pydantic import BeforeValidator
from pydantic import Field

from kyckr_mcp.mcp.inputs.company import blank_to_none
from kyckr_mcp.mcp.inputs.company import Text


def _order_id(value: object) -> object:
    return str(value).strip() if isinstance(value, str | int) else value


ProductId = Annotated[
    Text,
    Field(
        description=(
            "Product id of the document to order. Use the `id` of an entry returned by "
            "`list_company_documents`. Do not construct or guess."
        )
    ),
]
OrderId = Annotated[
    str | int,
    BeforeValidator(_order_id),
    Field(
        min_length=1,
        description=(
            "Order id returned by `create_document_order.data.orderId` or seen in "
            "`list_orders.data.orders[].orderId`. May be a string or a number, pass it as-is."
        ),
    ),
]
StartDate = Annotated[
    str | None,
    BeforeValidator(blank_to_none),
    Field(description="Earliest order date to include, ISO 8601, forwarded to Kyckr as given."),
]
EndDate = Annotated[
    str | None,
    BeforeValidator(blank_to_none),
    Field(description="Latest order date to include, ISO 8601, forwarded to Kyckr as given."),
]
