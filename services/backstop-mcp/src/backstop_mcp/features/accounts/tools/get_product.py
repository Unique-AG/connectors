"""`get_product`: one product or the catalog, with custom-field values.

Strategy, Domicile, Fee Structure and the rest live here — not on get_product_investors
(owners only) and not on list_custom_fields (definitions only).
"""

import asyncio
from collections.abc import Sequence
from http import HTTPStatus
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.accounts import (
    MAX_PRODUCT_SCAN_RECORDS,
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
    scan_truncated: bool = Field(
        default=False,
        description=(
            f"True when the catalog walk stopped at the {MAX_PRODUCT_SCAN_RECORDS}-product scan "
            "ceiling, so `products` is a prefix of the catalog. An absent Strategy then means "
            "'not in what was read', not 'not in the firm'. Always false for a single product."
        ),
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
        catalog = await fetch_product_catalog(client)
        # Concurrently: the catalog is ~72 rows and each row is a catalog join, so a sequential
        # comprehension is 72 awaits in a row for work that has no ordering between rows.
        products = await asyncio.gather(
            *(
                _record(client, custom_fields, item, names=custom_field_names)
                for item in catalog.products
            )
        )
        return ProductResolvedResponse(
            products=tuple(products), scan_truncated=catalog.scan_truncated
        )

    if product_id is not None:
        # A trusted id goes straight to the full record. Resolving it first would GET the same
        # product twice — once sparse to confirm it exists, once in full — and the full read
        # already carries `name` and `configuration`, and already 404s when it does not exist.
        return await _by_trusted_id(
            client, custom_fields, product_id=product_id, names=custom_field_names
        )

    assert product is not None
    outcome = await resolve_product_query(ctx, client, query=product)
    if not isinstance(outcome, Resolved):
        return ProductAmbiguousResponse.from_unresolved(outcome)

    item = await fetch_product(client, product_id=outcome.value.id)
    return ProductResolvedResponse(
        products=(await _record(client, custom_fields, item, names=custom_field_names),)
    )


async def _by_trusted_id(
    client: BackstopClient,
    custom_fields: CustomFieldsService,
    *,
    product_id: str,
    names: Sequence[str],
) -> GetProductResponse:
    """One by-id GET. A 404 is `not_found`; every other error stays an error.

    Backstop answers `GET /products/{non-digit}` with 400 rather than 404, so a value that is
    not an id is reported as an error rather than silently searched — `product` is the parameter
    for a name.
    """
    try:
        item = await fetch_product(client, product_id=product_id)
    except BackstopApiError as exc:
        if exc.status_code != HTTPStatus.NOT_FOUND:
            raise
        return NotFoundResponse(query=product_id, scope="products")
    return ProductResolvedResponse(
        products=(await _record(client, custom_fields, item, names=names),)
    )
