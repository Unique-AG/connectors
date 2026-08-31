"""`get_product`: one product or the catalog, with custom-field values.

Strategy, Domicile, Fee Structure and the rest live here — not on get_product_investors
(owners only) and not on list_custom_fields (definitions only).
"""

import asyncio
from collections.abc import Sequence
from http import HTTPStatus
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.accounts import (
    GetProductQuery,
    ProductAmbiguousResponse,
    ProductFetchDto,
    ProductRecordResponse,
    ProductResolvedResponse,
    resolve_product_query,
)
from backstop_mcp.features.accounts.dependencies import get_product_query_factory
from backstop_mcp.features.custom_fields import (
    CustomFieldFilters,
    CustomFieldsService,
    get_custom_fields_service,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import published_output_schema

type GetProductResponse = ProductAmbiguousResponse | NotFoundResponse | ProductResolvedResponse


async def _record(
    client: BackstopClient,
    custom_fields: CustomFieldsService,
    fetched: ProductFetchDto,
    *,
    names: Sequence[str],
) -> ProductRecordResponse:
    values = await custom_fields.join_values(
        client,
        fetched.stored_custom_field_values,
        filters=CustomFieldFilters(names=tuple(names)),
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
                "Omit together with `product` and `search` to walk the catalog."
            ),
        ),
    ] = None,
    product: Annotated[
        str | None,
        Field(
            description=(
                "Product short name (`CGUP`) or display name. Same lookup as `search`. "
                "Duplicate short names are ambiguous. Omit together with `product_id` and "
                "`search` to walk the catalog."
            ),
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            description=(
                "Product short name (`CGUP`) or display name — same lookup as `product`. "
                "Use this the way get_person uses `search`. Duplicate short names are "
                "ambiguous. Omit together with `product_id` and `product` to walk the catalog."
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
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    custom_fields: CustomFieldsService = Depends(get_custom_fields_service),
    get_product_query: GetProductQuery = Depends(get_product_query_factory),
) -> GetProductResponse:
    """Product identity and custom-field values — Strategy, Domicile, Fee Structure, and the rest.

    Pass a trusted `product_id`, or `search` / `product` (short name or display name) for one
    product. `search` is the same name lookup as on get_person. Omit all three to walk the
    catalog in one request (this instance has ~72 products). That is how you answer "which of
    our products are Convertible Arbitrage": walk with `custom_field_names=["Strategy"]` and
    read the values. Do not iterate `get_product_investors` or `get_time_series` for this —
    those tools do not publish product custom fields.
    """
    if product is not None and search is not None:
        raise ValueError("Pass at most one of product or search")
    name = product if product is not None else search
    if product_id is not None and name is not None:
        raise ValueError("Pass at most one of product_id or product/search")

    if product_id is None and name is None:
        # Overlap the product walk with a schema-cache warm. Each of the ~72 rows then joins
        # against a filled catalog; the load return is unused because `_record` reads the cache.
        catalog, _ = await asyncio.gather(
            get_product_query.catalog(),
            custom_fields.load_catalog(client),
        )
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
            client,
            custom_fields,
            get_product_query,
            product_id=product_id,
            names=custom_field_names,
        )

    assert name is not None
    outcome = await resolve_product_query(ctx, client, query=name)
    if not isinstance(outcome, Resolved):
        return ProductAmbiguousResponse.from_unresolved(outcome)

    item, _ = await asyncio.gather(
        get_product_query.run(product_id=outcome.value.id),
        custom_fields.load_catalog(client),
    )
    return ProductResolvedResponse(
        products=(await _record(client, custom_fields, item, names=custom_field_names),)
    )


async def _by_trusted_id(
    client: BackstopClient,
    custom_fields: CustomFieldsService,
    get_product_query: GetProductQuery,
    *,
    product_id: str,
    names: Sequence[str],
) -> GetProductResponse:
    """One by-id GET. A 404 is `not_found`; every other error stays an error.

    Backstop answers `GET /products/{non-digit}` with 400 rather than 404, so a value that is
    not an id is reported as an error rather than silently searched — `search` (or `product`)
    is the parameter for a name.
    """
    try:
        item, _ = await asyncio.gather(
            get_product_query.run(product_id=product_id),
            custom_fields.load_catalog(client),
        )
    except BackstopApiError as exc:
        if exc.status_code != HTTPStatus.NOT_FOUND:
            raise
        return NotFoundResponse(query=product_id, scope="products")
    return ProductResolvedResponse(
        products=(await _record(client, custom_fields, item, names=names),)
    )
