"""Resolve a Backstop product from a trusted id, a short name, or a name.

Do not route this through `resolve_party`. That primitive is trusted id or `/quick-search` of a
display name. Product callers also type `productShortName` (`CGUP`), and that path is not covered:

- `GET /quick-search?filter[searchTypes][eq]=PRODUCT` for `CGUP` is empty.
- `GET /products?filter[shortName][eq]=…` is `400`.
- Searching the same string as `ORGANIZATION` can hit a CRM company whose id no account
  `filter[product.id]` accepts.

A trusted `product_id` is read straight from `GET /products/{id}?fields=name,configuration`, and
a 404 is the `not_found`. That is one 300-byte request that cannot be defeated by catalog size,
which is what an echoed id needs — from a prior resolve, or handed back by
`get_accounts_for_party`.

A name or short name has no by-id equivalent. `/products` accepts `filter[name][like]`, but
`shortName` is not a filter field (`filter[shortName][eq]` is 400), so a LIKE on a short name
like `CGUP` returns empty. Name search therefore tries `filter[name][like]` first (one request
for "Dispersion"), and only walks the unfiltered catalog when that misses — which is what
`productShortName` needs. Duplicate short names (`BLUC`) go through one `elicit_choice`. The
same response hydrates `short_name`.

Walking the catalog to the end is what lets `not_found` mean *absent* instead of *not on this
page*. The catalog is small enough for that: this instance returns 72 in one page, all with a
`productShortName`, three of them duplicated (`PKAP`, `BLUC`, `CPOL`). Past `_LARGE_CATALOG` the
assumption is no longer safe — re-reading the whole catalog per search starts costing real
requests, and a TTL cache like the opportunity-stage vocabulary would be the answer. So that
case warns rather than passing silently.
"""

import logging
from collections.abc import Sequence
from http import HTTPStatus
from urllib.parse import quote

from fastmcp import Context

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.accounts.api_responses import ProductAttributes
from backstop_mcp.features.accounts.internal_dto import ProductResolution, ResolvedProductDto
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

# Two full pages. This instance returns 72, so anything past this is a different kind of tenant
# and the "re-read the catalog every call" trade stops paying for itself.
_LARGE_CATALOG = 400

_SCOPE = "products"

# Plain assignments — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
_ProductResource = BackstopApiResource[ProductAttributes]
_ProductDocument = BackstopApiResourceDocument[ProductAttributes]


def _product_label(product: ResolvedProductDto) -> str:
    if product.name is not None and product.short_name is not None:
        return f"{product.name} ({product.short_name})"
    if product.name is not None:
        return product.name
    if product.short_name is not None:
        return product.short_name
    return product.id


def _resolution(hits: Sequence[ResolvedProductDto], *, query: str) -> ProductResolution:
    return from_candidates(
        tuple(
            Candidate(key=product.id, label=_product_label(product), value=product)
            for product in hits
        ),
        query=query,
        scope=_SCOPE,
    )


def _match_product(products: Sequence[ResolvedProductDto], query: str) -> ProductResolution:
    """Match `query` against a parsed product index.

    Order: exact id, exact short name, exact name, name substring. A caller can type an id into
    `product`, so the id match stays here even though `product_id=` is answered by id lookup.
    """
    query = query.strip()
    if not query:
        return NotFound(query=query, scope=_SCOPE)

    id_hits = tuple(product for product in products if product.id == query)
    if id_hits:
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


async def _fetch_product(client: BackstopClient, product_id: str) -> ProductResolution:
    """Read one product by trusted id, or `NotFound` when Backstop holds no such record.

    Only a missing record is an answer; every other error stays an error, so a permissions or
    transport failure is never reported to the model as "no such product". `require_data` is
    inside the `try` so that both shapes Backstop uses for a missing record reach the same
    `NotFound` — a real 404, which is what `/products/{unknown}` sends, and the
    `200 {"data": null}` some other by-id endpoints answer with instead.
    """
    product_id = product_id.strip()
    if not product_id:
        return NotFound(query=product_id, scope=_SCOPE)

    path = f"{_PRODUCTS_PATH}/{quote(product_id, safe='')}"
    try:
        document = await client.get(
            path, params={"fields": _PRODUCT_FIELDS}, schema=_ProductDocument
        )
        resource = document.require_data(path=path)
    except BackstopApiError as exc:
        if exc.status_code != HTTPStatus.NOT_FOUND:
            raise
        return NotFound(query=product_id, scope=_SCOPE)

    return _resolution(
        (ResolvedProductDto.from_attributes(resource.id, resource.attributes),), query=product_id
    )


async def _index_products(
    client: BackstopClient, *, name_like: str | None = None
) -> tuple[ResolvedProductDto, ...]:
    params: dict[str, object] = {"fields": _PRODUCT_FIELDS}
    if name_like is not None:
        params["filter[name][like]"] = name_like
    page = await client.paginate(
        _PRODUCTS_PATH,
        schema=_ProductResource,
        params=params,
        max_records=None,
        page_size=_PRODUCT_INDEX_PAGE_SIZE,
    )
    products = tuple(
        ResolvedProductDto.from_attributes(resource.id, resource.attributes)
        for resource in page.items
    )
    if len(products) > _LARGE_CATALOG:
        logger.warning(
            "accounts.products.index_large",
            extra={
                "returned": len(products),
                "total_count": page.total_count,
                "threshold": _LARGE_CATALOG,
            },
        )
    return products


async def resolve_product(
    ctx: Context,
    client: BackstopClient,
    *,
    product_id: str | None = None,
    product: str | None = None,
) -> ProductResolution:
    """Resolve one product from a trusted id, a short name, or a name search.

    Exactly one of `product_id` or `product` must be set. A trusted id is one by-id request; a
    name search uses `filter[name][like]` first, then the unfiltered catalog when that misses
    (short names are not filterable). Ambiguous matches elicit once.
    """
    assert (product_id is None) != (product is None), (
        "Exactly one of product_id or product must be provided"
    )

    if product_id is not None:
        return await _fetch_product(client, product_id)

    assert product is not None
    if not product.strip():
        return NotFound(query=product.strip(), scope=_SCOPE)
    outcome = _match_product(await _index_products(client, name_like=product), product)
    if isinstance(outcome, NotFound):
        outcome = _match_product(await _index_products(client), product)
    if isinstance(outcome, Ambiguous):
        return await elicit_choice(
            ctx,
            outcome,
            prompt=(f'Multiple {outcome.scope} matched "{outcome.query}". Which one did you mean?'),
        )
    return outcome


async def resolve_product_query(
    ctx: Context, client: BackstopClient, *, query: str
) -> ProductResolution:
    """Resolve a product from one string that may be an id, a short name, or a display name.

    Digits are a by-id GET, then the catalog if that id is missing. Anything else is the
    catalog only — Backstop answers `GET /products/{non-digit}` with 400, not 404, so a
    short name must never be sent as a path segment.
    """
    query = query.strip()
    if not query:
        return NotFound(query=query, scope=_SCOPE)
    if not query.isdigit():
        return await resolve_product(ctx, client, product=query)
    by_id = await resolve_product(ctx, client, product_id=query)
    if not isinstance(by_id, NotFound):
        return by_id
    return await resolve_product(ctx, client, product=query)
