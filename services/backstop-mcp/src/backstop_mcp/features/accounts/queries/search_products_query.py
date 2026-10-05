"""Search the product catalog with the filters Backstop can apply, then the ones it cannot.

`GET /products` filters on `name` (`like`, case-insensitive substring), `modifiedTimestamp`,
`createdTimestamp`, and `otherId`. `productType`, `isOnshore`, `shortName`, and custom fields are
400 there, so those narrow after the read. No sparse fieldset: `regularCustomFieldValues` is
stripped by `fields=`.

A `name` that no product name contains is tried as a whole short name over an unfiltered walk,
because `productShortName` is not a `/products` filter.
"""

from collections.abc import Sequence
from datetime import date

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
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
        """AND across filters. `product_ids` and each predicate's values are OR within."""
        name = (name or "").strip() or None
        base: dict[str, object] = {"sort": "name"}
        if modified_since is not None:
            base["filter[modifiedTimestamp][gt]"] = modified_since.isoformat()

        if name is None:
            fetched = await self._walk(base)
        else:
            fetched = await self._walk({**base, "filter[name][like]": name})
            if not fetched.products:
                fetched = await self._by_short_name(base, name)

        ids = frozenset(item.strip() for item in product_ids if item.strip())
        type_needle = product_type.strip().casefold() if product_type else None
        predicates = normalize_matches(custom_fields)
        return ProductCatalogFetchDto(
            products=tuple(
                item
                for item in fetched.products
                if (not ids or item.product.id in ids)
                and (type_needle is None or (item.product_type or "").casefold() == type_needle)
                and (is_onshore is None or item.is_onshore is is_onshore)
                and satisfies_every(item.stored_custom_field_values, predicates)
            )
        )

    async def _by_short_name(self, base: dict[str, object], name: str) -> ProductCatalogFetchDto:
        needle = name.casefold()
        fetched = await self._walk(base)
        return ProductCatalogFetchDto(
            products=tuple(
                item
                for item in fetched.products
                if item.product.short_name is not None
                and item.product.short_name.casefold() == needle
            )
        )

    async def _walk(self, params: dict[str, object]) -> ProductCatalogFetchDto:
        page = await self._client.paginate(
            _PRODUCTS_PATH,
            schema=_ProductResource,
            params=params,
            max_records=None,
            page_size=_PAGE_SIZE,
        )
        return ProductCatalogFetchDto(
            products=tuple(ProductFetchDto.from_resource(resource) for resource in page.items)
        )
