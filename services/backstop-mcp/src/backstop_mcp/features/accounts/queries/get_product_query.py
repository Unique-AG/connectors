"""Fetch one product or the product catalog with custom-field values intact.

Name resolution still uses the sparse `fields=name,configuration` index. This layer is the
full record `get_product` joins to the custom-field catalog — no `fields=` so
`regularCustomFieldValues` is not stripped.
"""

import logging
from urllib.parse import quote

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.accounts.api_responses import ProductAttributes
from backstop_mcp.features.accounts.internal_dto import ProductCatalogFetchDto, ProductFetchDto
from backstop_mcp.features.accounts.responses import MAX_PRODUCT_SCAN_RECORDS

logger = logging.getLogger(__name__)

_PRODUCTS_PATH = "/products"
_PAGE_SIZE = 200

_ProductResource = BackstopApiResource[ProductAttributes]
_ProductDocument = BackstopApiResourceDocument[ProductAttributes]


class GetProductQuery:
    """The full product record, or the catalog walk, with stored custom-field values."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, product_id: str) -> ProductFetchDto:
        """GET /products/{id} with the full attribute set, including custom-field values."""
        path = f"{_PRODUCTS_PATH}/{quote(product_id, safe='')}"
        document = await self._client.get(path, schema=_ProductDocument)
        return ProductFetchDto.from_resource(document.require_data(path=path))

    async def catalog(self) -> ProductCatalogFetchDto:
        """Walk /products with no sparse fieldset so custom-field values arrive on each row."""
        page = await self._client.paginate(
            _PRODUCTS_PATH,
            schema=_ProductResource,
            max_records=MAX_PRODUCT_SCAN_RECORDS,
            page_size=_PAGE_SIZE,
        )
        if page.truncated:
            logger.warning(
                "accounts.products.catalog_scan_ceiling_reached",
                extra={"ceiling": MAX_PRODUCT_SCAN_RECORDS, "total_count": page.total_count},
            )
        return ProductCatalogFetchDto(
            products=tuple(ProductFetchDto.from_resource(resource) for resource in page.items),
            scan_truncated=page.truncated,
        )
