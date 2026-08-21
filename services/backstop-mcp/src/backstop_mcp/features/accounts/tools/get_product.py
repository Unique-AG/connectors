"""`get_product`: one product or the catalog, with custom-field values.

Strategy, Domicile, Fee Structure and the rest live here — not on get_product_investors
(owners only) and not on list_custom_fields (definitions only).
"""

from collections.abc import Sequence
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.accounts import (
    ProductAmbiguousResponse,
    ProductFetchDto,
    fetch_product,
    fetch_product_catalog,
    resolve_product_query,
)
from backstop_mcp.features.custom_fields import (
    CustomFieldsService,
    ResolvedCustomFieldValueResponse,
    get_custom_fields_service,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import OmitNoneModel, published_output_schema


class ProductRecordResponse(OmitNoneModel):
    """One product identity plus its custom-field values."""

    id: str = Field(
        description=(
            "Backstop product id. Echo it as `entity_id` on `get_time_series` with "
            "`entity_type='products'` — never invent one."
        )
    )
    name: str | None = Field(default=None, description="Product name as Backstop stores it.")
    short_name: str | None = Field(
        default=None,
        description="`productShortName` (e.g. 'CGUP'). Tenants may call this a fund or vehicle.",
    )
    custom_field_values: list[ResolvedCustomFieldValueResponse] = Field(
        default_factory=list,
        description=(
            "Custom-field values on this product joined to list_custom_fields definitions "
            "(Strategy, Domicile, Fee Structure, …). Empty when the record has none or the "
            "catalog could not be loaded. Slice with custom_field_names rather than fetching again."
        ),
    )


class ProductResolvedResponse(OmitNoneModel):
    """`get_product` once products were fetched and custom fields joined."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the product catalog or the named product was fetched.",
    )
    products: tuple[ProductRecordResponse, ...] = Field(
        description=(
            "Matching products. One item when a name or id was passed; the catalog when neither "
            "was. The catalog is small (~72 on this instance) — this is one walk, not a "
            "per-product fan-out."
        )
    )


type GetProductResponse = ProductAmbiguousResponse | NotFoundResponse | ProductResolvedResponse


async def _record(
    client: BackstopClient,
    custom_fields: CustomFieldsService,
    fetched: ProductFetchDto,
    *,
    names: Sequence[str],
) -> ProductRecordResponse:
    values = await custom_fields.resolve_values(
        client, fetched.stored_custom_field_values, names=names
    )
    return ProductRecordResponse(
        id=fetched.product.id,
        name=fetched.product.name,
        short_name=fetched.product.short_name,
        custom_field_values=values,
    )


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetProductResponse),
)
async def get_product(
    ctx: Context,
    product_id: Annotated[
        str | None,
        Field(
            description=(
                "Trusted Backstop product id from a prior resolve echo. Never invent one. "
                "Omit together with `product` to walk the catalog."
            ),
        ),
    ] = None,
    product: Annotated[
        str | None,
        Field(
            description=(
                "Product short name (`CGUP`) or display name. Duplicate short names are "
                "ambiguous. Omit together with `product_id` to walk the catalog."
            ),
        ),
    ] = None,
    custom_field_names: Annotated[
        Sequence[str],
        Field(
            description=(
                "Custom-field names whose values to keep, e.g. Strategy. Case-insensitive. "
                "Omit to keep every name."
            ),
        ),
    ] = (),
    client: BackstopClient = Depends(get_backstop_client),
    custom_fields: CustomFieldsService = Depends(get_custom_fields_service),
) -> GetProductResponse:
    """Product identity and custom-field values — Strategy, Domicile, Fee Structure, and the rest.

    Pass a trusted `product_id` or `product` (short name or display name) for one product.
    Omit both to walk the catalog in one request (this instance has ~72 products). That is how
    you answer "which of our products are Convertible Arbitrage": walk with
    `custom_field_names=["Strategy"]` and read the values. Do not iterate `get_product_investors`
    or `get_time_series` for this — those tools do not publish product custom fields.
    """
    if product_id is not None and product is not None:
        raise ValueError("Pass at most one of product_id or product")

    if product_id is None and product is None:
        fetched = await fetch_product_catalog(client)
        products = tuple(
            [
                await _record(client, custom_fields, item, names=custom_field_names)
                for item in fetched
            ]
        )
        return ProductResolvedResponse(products=products)

    query = product_id if product_id is not None else product
    assert query is not None
    outcome = await resolve_product_query(ctx, client, query=query)
    if not isinstance(outcome, Resolved):
        return ProductAmbiguousResponse.from_unresolved(outcome)

    item = await fetch_product(client, product_id=outcome.value.id)
    return ProductResolvedResponse(
        products=(await _record(client, custom_fields, item, names=custom_field_names),)
    )
