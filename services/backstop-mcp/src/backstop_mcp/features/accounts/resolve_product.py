"""Resolve a Backstop product from a trusted id, a short name, or a name.

Not `ResolvePartyQuery`: `/quick-search` misses `productShortName` (`NGUP`), and
`filter[shortName]` is not a `/products` filter (400). A trusted id is one
`GET /products/{id}?fields=name,configuration`; a 404 is `not_found`. A name tries
`filter[name][like]` first and walks the whole catalog only when that misses, so a short name
still resolves and `not_found` means *absent*, not *not on this page*. Past `_LARGE_CATALOG`
that per-search walk stops being cheap, so it logs a warning.
"""

import logging
from collections.abc import Sequence
from http import HTTPStatus
from typing import ClassVar, Literal
from urllib.parse import quote

from fastmcp import Context
from mcp.types import InputRequiredResult
from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopApiResource,
    BackstopApiSingleResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.accounts.api_responses import ProductAttributes
from backstop_mcp.features.accounts.internal_dto import ProductResolution, ResolvedProductDto
from backstop_mcp.features.resolution import (
    Ambiguous,
    Candidate,
    NotFound,
    Resolved,
    Unresolved,
    elicit_if_ambiguous,
    from_candidates,
    input_required,
)

logger = logging.getLogger(__name__)

_PRODUCTS_PATH = "/products"
_PRODUCT_FIELDS = "name,configuration"
_PRODUCT_INDEX_PAGE_SIZE = 200

# Two full pages. Past this the "re-read the catalog every call" trade stops paying for itself.
_LARGE_CATALOG = 400

_FAMILY_CAP = 6

_SCOPE = "products"

# Plain assignments — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
_ProductResource = BackstopApiResource[ProductAttributes]
_ProductDocument = BackstopApiSingleResourceDocument[ProductAttributes]


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


class _ProductMatch(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    resolution: ProductResolution
    field: Literal["id", "short_name", "exact_name", "substring", "none"]


def _match_product(products: Sequence[ResolvedProductDto], query: str) -> _ProductMatch:
    """Match `query` against a parsed product index.

    Order: exact id, exact short name, exact name, name substring. A caller can type an id into
    `product`, so the id match stays here even though `product_id=` is answered by id lookup.
    """
    query = query.strip()
    if not query:
        return _ProductMatch(resolution=NotFound(query=query, scope=_SCOPE), field="none")

    id_hits = tuple(product for product in products if product.id == query)
    if id_hits:
        return _ProductMatch(resolution=_resolution(id_hits, query=query), field="id")

    needle = query.casefold()
    short_hits = tuple(
        product
        for product in products
        if product.short_name is not None and product.short_name.casefold() == needle
    )
    if short_hits:
        return _ProductMatch(resolution=_resolution(short_hits, query=query), field="short_name")

    exact_name_hits = tuple(
        product
        for product in products
        if product.name is not None and product.name.casefold() == needle
    )
    if exact_name_hits:
        return _ProductMatch(
            resolution=_resolution(exact_name_hits, query=query), field="exact_name"
        )

    substring_hits = tuple(
        product
        for product in products
        if product.name is not None and needle in product.name.casefold()
    )
    return _ProductMatch(resolution=_resolution(substring_hits, query=query), field="substring")


def _select_product_family(
    products: Sequence[ResolvedProductDto], query: str
) -> ProductResolution | tuple[ResolvedProductDto, ...]:
    """Substring hits up to `_FAMILY_CAP` come back together. Anything else is today's match.

    A duplicate short name or exact name stays ambiguous. More substring hits than the cap
    falls back to that same elicitation.
    """
    match = _match_product(products, query)
    if match.field == "substring" and isinstance(match.resolution, Ambiguous):
        hits = tuple(candidate.value for candidate in match.resolution.candidates)
        if len(hits) <= _FAMILY_CAP:
            return hits
    return match.resolution


async def _fetch_product(client: BackstopClient, product_id: str) -> ProductResolution:
    """Read one product by trusted id, or `NotFound` when Backstop holds no such record.

    Only a missing record is an answer; every other error stays an error, so a permissions or
    transport failure is never reported to the model as "no such product". `/products/{unknown}`
    404s, so a caught `NOT_FOUND` is the missing-record path.
    """
    product_id = product_id.strip()
    if not product_id:
        return NotFound(query=product_id, scope=_SCOPE)

    path = f"{_PRODUCTS_PATH}/{quote(product_id, safe='')}"
    try:
        document = await client.get(
            path, params={"fields": _PRODUCT_FIELDS}, schema=_ProductDocument
        )
        resource = document.data
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
) -> ProductResolution | InputRequiredResult:
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
    outcome = _match_product(await _index_products(client, name_like=product), product).resolution
    if isinstance(outcome, NotFound):
        outcome = _match_product(await _index_products(client), product).resolution
    return await elicit_if_ambiguous(ctx, outcome)


async def resolve_product_family(
    ctx: Context,
    client: BackstopClient,
    *,
    product: str,
) -> tuple[ResolvedProductDto, ...] | Unresolved[ResolvedProductDto] | InputRequiredResult:
    """Like `resolve_product`, except a name-substring match returns every vehicle up to the cap.

    Digits are tried as a by-id GET first, the same way `resolve_product_query` does, so an
    echoed id stays one request. A duplicate short name or exact name still elicits. More
    substring hits than `_FAMILY_CAP` elicits too.
    """
    product = product.strip()
    if not product:
        return NotFound(query=product, scope=_SCOPE)
    if product.isdigit():
        by_id = await _fetch_product(client, product)
        if isinstance(by_id, Resolved):
            return (by_id.value,)
    selected = _select_product_family(await _index_products(client, name_like=product), product)
    if isinstance(selected, tuple):
        return selected
    if isinstance(selected, NotFound):
        selected = _select_product_family(await _index_products(client), product)
        if isinstance(selected, tuple):
            return selected
    outcome = await elicit_if_ambiguous(ctx, selected)
    if input_required(outcome) or not isinstance(outcome, Resolved):
        return outcome
    return (outcome.value,)


async def resolve_product_query(
    ctx: Context, client: BackstopClient, *, query: str
) -> ProductResolution | InputRequiredResult:
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
