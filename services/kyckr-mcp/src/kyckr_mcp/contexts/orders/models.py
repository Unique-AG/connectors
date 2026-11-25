from pydantic import Field

from kyckr_mcp.contexts.replies import Cost
from kyckr_mcp.contexts.replies import KyckrModel
from kyckr_mcp.contexts.replies import Reply


class OrderedProduct(KyckrModel):
    """The document an order is for."""

    product_name: str | None = Field(None, description="The name of the document.")
    product_category: str | None = Field(None, description="The kind of document.")


class OrderedCompany(KyckrModel):
    """The company an order is about."""

    company_name: str | None = Field(None, description="The name of the company.")
    company_number: str | None = Field(None, description="Its registration number.")
    kyckr_id: str | None = Field(None, description="Its Kyckr id.")


class Order(KyckrModel):
    """A Kyckr order for a registry document or profile."""

    order_id: str | int | None = Field(None, description="The order id, for `get_order`.")
    order_date: str | None = Field(None, description="When the order was placed.")
    status: str | None = Field(None, description="`Pending`, `Success` or `Failed`.")
    cost: Cost | None = Field(None, description="What the order cost.")
    product_details: OrderedProduct | None = Field(None, description="What was ordered.")
    company_details: OrderedCompany | None = Field(
        None, description="The company it was ordered for."
    )
    document_json: dict[str, object] | None = Field(
        None,
        description=(
            "Structured view of the ordered document, added once `status` is `Success`. Field "
            "names are PascalCase (Kyckr download-endpoint convention). Absent while `status` is "
            "`Pending` or `Failed`, and when the registry has no JSON view of the filing, in "
            "which case `details` says the document is PDF-only."
        ),
    )


class OrderReply(Reply):
    """An order, with its document once it finished."""

    data: Order | None = Field(None, description="The order.")
