"""Search the product catalog: one read, then every filter Backstop cannot apply.

`GET /products` filters on `modifiedTimestamp`; `productType`, `isOnshore`, `shortName`, and
custom fields are 400 there, so those narrow after the read. No sparse fieldset:
`regularCustomFieldValues` is stripped by `fields=`.

`name` is matched in memory over the unfiltered catalog, not sent as `filter[name][like]`:
`productShortName` is not filterable, and an exact short name has to win over a name that merely
contains it (`ARB` over 'Convert Arb Fund'), which a server-side pre-pass would hide.

`product_ids` reads those products by id instead of the catalog. A by-id GET without `fields=`
carries the same attributes as a listing row, so every other filter then applies in memory.
"""

import asyncio
from collections.abc import Sequence
from datetime import date
from http import HTTPStatus
from urllib.parse import quote

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopApiResource,
    BackstopApiSingleResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.accounts.api_responses import ProductAttributes
from backstop_mcp.features.accounts.internal_dto import ProductCatalogFetchDto, ProductFetchDto
from backstop_mcp.features.custom_fields import (
    CustomFieldMatch,
    normalize_matches,
    satisfies_every,
)

_PRODUCTS_PATH = "/products"
_PAGE_SIZE = 200

_ProductResource = BackstopApiResource[ProductAttributes]
_ProductDocument = BackstopApiSingleResourceDocument[ProductAttributes]


class SearchProductsQuery:
    """The products that satisfy every filter given, with stored custom-field values."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        name: str | None = None,
        modified_since: date | None = None,
        product_ids: Sequence[str] = (),
        product_type: str | None = None,
        is_onshore: bool | None = None,
        custom_fields: Sequence[CustomFieldMatch] = (),
    ) -> ProductCatalogFetchDto:
        """AND across filters. `product_ids` and each predicate's values are OR within.

        Exact short-name hits come first, then name-substring hits; each group keeps name order.
        """
        name = (name or "").strip() or None
        ids = tuple(dict.fromkeys(item.strip() for item in product_ids if item.strip()))
        if ids:
            fetched = await self._by_ids(ids, modified_since=modified_since)
        else:
            params: dict[str, object] = {"sort": "name"}
            if modified_since is not None:
                params["filter[modifiedTimestamp][gt]"] = modified_since.isoformat()
            fetched = await self._fetch_all(params)

        type_needle = product_type.strip().casefold() if product_type else None
        predicates = normalize_matches(custom_fields)
        return ProductCatalogFetchDto(
            products=tuple(
                item
                for item in (fetched if name is None else self._by_name(fetched, name))
                if (type_needle is None or (item.product_type or "").casefold() == type_needle)
                and (is_onshore is None or item.is_onshore is is_onshore)
                and satisfies_every(item.stored_custom_field_values, predicates)
            )
        )

    @staticmethod
    def _by_name(products: Sequence[ProductFetchDto], name: str) -> tuple[ProductFetchDto, ...]:
        """Exact short-name hits first, then the other products whose name contains `name`."""
        needle = name.casefold()

        def is_short_name(item: ProductFetchDto) -> bool:
            short_name = item.product.short_name
            return short_name is not None and short_name.casefold() == needle

        return tuple(item for item in products if is_short_name(item)) + tuple(
            item
            for item in products
            if not is_short_name(item)
            and item.product.name is not None
            and needle in item.product.name.casefold()
        )

    async def _fetch_all(self, params: dict[str, object]) -> tuple[ProductFetchDto, ...]:
        page = await self._client.paginate(
            _PRODUCTS_PATH,
            schema=_ProductResource,
            params=params,
            max_records=None,
            page_size=_PAGE_SIZE,
        )
        return tuple(ProductFetchDto.from_resource(resource) for resource in page.items)

    async def _by_ids(
        self, ids: Sequence[str], *, modified_since: date | None
    ) -> tuple[ProductFetchDto, ...]:
        """Each id's product, sorted by name like the catalog read; missing ids are dropped.

        Concurrently: the ids are independent GETs, and the catalog walk this replaces would read
        every product to find a handful. `filter[modifiedTimestamp][gt]=<date>` keeps only
        products modified on a later day (a same-day edit is excluded, probed live), so the
        in-memory check compares dates.
        """
        fetched = await asyncio.gather(*(self._one(product_id) for product_id in ids))
        return tuple(
            sorted(
                (
                    item
                    for item in fetched
                    if item is not None
                    and (
                        modified_since is None
                        or (
                            item.modified_timestamp is not None
                            and item.modified_timestamp.date() > modified_since
                        )
                    )
                ),
                key=lambda item: (item.product.name is None, (item.product.name or "").casefold()),
            )
        )

    async def _one(self, product_id: str) -> ProductFetchDto | None:
        """One product, or `None` when Backstop holds no such id.

        Probed live: a missing int id is 404 `ResourceNotFoundException`; a non-digit or
        out-of-int-range id is 400 `InvalidParameterException`. This GET sends no params, so a
        400 can only be about the id. Every other error stays an error.
        """
        try:
            document = await self._client.get(
                f"{_PRODUCTS_PATH}/{quote(product_id, safe='')}", schema=_ProductDocument
            )
        except BackstopApiError as exc:
            if exc.status_code not in (HTTPStatus.NOT_FOUND, HTTPStatus.BAD_REQUEST):
                raise
            return None
        return ProductFetchDto.from_resource(document.data)
