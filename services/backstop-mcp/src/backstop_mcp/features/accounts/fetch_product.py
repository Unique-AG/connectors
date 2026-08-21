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
from backstop_mcp.features.accounts.internal_dto import (
    ProductCatalogFetchDto,
    ProductFetchDto,
    ResolvedProductDto,
)

logger = logging.getLogger(__name__)

_PRODUCTS_PATH = "/products"
_PAGE_SIZE = 200

# Scan ceiling for the catalog walk. 72 products on this instance; `resolve_product` already
# warns past 400 because re-reading the catalog per search stops paying for itself. This is the
# hard stop above that warning, so a tenant with a pathological catalog gets a stated prefix
# rather than an unbounded read.
MAX_PRODUCT_SCAN_RECORDS = 2_000

_ProductResource = BackstopApiResource[ProductAttributes]
_ProductDocument = BackstopApiResourceDocument[ProductAttributes]


def _to_dto(resource: BackstopApiResource[ProductAttributes]) -> ProductFetchDto:
    return ProductFetchDto(
        product=ResolvedProductDto.from_attributes(resource.id, resource.attributes),
        stored_custom_field_values=resource.attributes.regular_custom_field_values,
    )


async def fetch_product(client: BackstopClient, *, product_id: str) -> ProductFetchDto:
    """GET /products/{id} with the full attribute set, including custom-field values."""
    path = f"{_PRODUCTS_PATH}/{quote(product_id, safe='')}"
    document = await client.get(path, schema=_ProductDocument)
    return _to_dto(document.require_data(path=path))


async def fetch_product_catalog(client: BackstopClient) -> ProductCatalogFetchDto:
    """Walk /products with no sparse fieldset so custom-field values arrive on each row."""
    page = await client.paginate(
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
        products=tuple(_to_dto(resource) for resource in page.items),
        scan_truncated=page.truncated,
    )
