"""Resolve a Backstop product from a trusted id, a short name, or a name.

Do not route this through `resolve_party`. That primitive is trusted id or `/quick-search` of a
display name. Product callers also type `productShortName` (`CGUP`), and that path is not covered:

- `GET /quick-search?filter[searchTypes][eq]=PRODUCT` for `CGUP` is empty.
- `GET /products?filter[shortName][eq]=…` is `400`.
- Searching the same string as `ORGANIZATION` can hit a CRM company whose id no account
  `filter[product.id]` accepts.

The catalog is one `GET /products?fields=name,configuration` page (limit 200). Match is local:
id, then exact `productShortName`, then exact name, then name substring. Duplicate short names
(`BLUC`) go through one `elicit_choice`. The same response hydrates `short_name`.
"""

import logging
from collections.abc import Sequence

from fastmcp import Context

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.accounts.types import (
    ProductAttributes,
    ProductResolution,
    ResolvedProduct,
)
from backstop_mcp.features.resolution import (
    Ambiguous,
    Candidate,
    NotFound,
    elicit_choice,
    from_candidates,
)

logger = logging.getLogger(__name__)

_PRODUCTS_PATH = "/products"
_PRODUCT_FIELDS = "name,configuration"
_PRODUCT_INDEX_PAGE_SIZE = 200
_SCOPE = "products"

# Plain assignment — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
_ProductResource = BackstopApiResource[ProductAttributes]


def product_label(product: ResolvedProduct) -> str:
    if product.name is not None and product.short_name is not None:
        return f"{product.name} ({product.short_name})"
    if product.name is not None:
        return product.name
    if product.short_name is not None:
        return product.short_name
    return product.id


def _resolution(hits: Sequence[ResolvedProduct], *, query: str) -> ProductResolution:
    return from_candidates(
        tuple(
            Candidate(key=product.id, label=product_label(product), value=product)
            for product in hits
        ),
        query=query,
        scope=_SCOPE,
    )


def match_product(
    products: Sequence[ResolvedProduct],
    query: str,
    *,
    id_only: bool = False,
) -> ProductResolution:
    """Match `query` against a parsed product index.

    Order: exact id, exact short name, exact name, name substring. `id_only` is the
    `product_id=` path: look up the id so the name is filled in, and do not fall through.
    """
    query = query.strip()
    if not query:
        return NotFound(query=query, scope=_SCOPE)

    id_hits = tuple(product for product in products if product.id == query)
    if id_only or id_hits:
        return _resolution(id_hits, query=query)

    needle = query.casefold()
    short_hits = tuple(
        product
        for product in products
        if product.short_name is not None and product.short_name.casefold() == needle
    )
    if short_hits:
        return _resolution(short_hits, query=query)

    exact_name_hits = tuple(
        product
        for product in products
        if product.name is not None and product.name.casefold() == needle
    )
    if exact_name_hits:
        return _resolution(exact_name_hits, query=query)

    substring_hits = tuple(
        product
        for product in products
        if product.name is not None and needle in product.name.casefold()
    )
    return _resolution(substring_hits, query=query)


async def resolve_product(
    ctx: Context,
    client: BackstopClient,
    *,
    product_id: str | None = None,
    product: str | None = None,
) -> ProductResolution:
    """Resolve one product from a trusted id, a short name, or a name search.

    Exactly one of `product_id` or `product` must be set. Ambiguous matches elicit once.
    """
    assert (product_id is None) != (product is None), (
        "Exactly one of product_id or product must be provided"
    )

    page = await client.fetch_page(
        _PRODUCTS_PATH,
        schema=_ProductResource,
        params={"fields": _PRODUCT_FIELDS},
        page_size=_PRODUCT_INDEX_PAGE_SIZE,
    )
    products = tuple(
        ResolvedProduct.from_attributes(resource.id, resource.attributes) for resource in page.items
    )
    truncated = page.next_path is not None or (
        page.total_count is not None and page.total_count > len(products)
    )
    if truncated:
        logger.warning(
            "accounts.products.index_truncated",
            extra={
                "returned": len(products),
                "total_count": page.total_count,
                "has_next": page.next_path is not None,
            },
        )

    if product_id is not None:
        outcome = match_product(products, product_id.strip(), id_only=True)
    else:
        assert product is not None
        outcome = match_product(products, product)

    if isinstance(outcome, Ambiguous):
        return await elicit_choice(
            ctx,
            outcome,
            prompt=(f'Multiple {outcome.scope} matched "{outcome.query}". Which one did you mean?'),
        )
    return outcome
