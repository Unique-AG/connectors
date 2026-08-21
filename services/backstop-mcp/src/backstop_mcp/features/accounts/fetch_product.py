"""Fetch one product or the product catalog with custom-field values intact.

Name resolution still uses the sparse `fields=name,configuration` index. This layer is the
full record `get_product` joins to the custom-field catalog — no `fields=` so
`regularCustomFieldValues` is not stripped.
"""

from urllib.parse import quote

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.accounts.api_responses import ProductAttributes
from backstop_mcp.features.accounts.internal_dto import ProductFetchDto, ResolvedProductDto

_PRODUCTS_PATH = "/products"
_PAGE_SIZE = 200

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


async def fetch_product_catalog(client: BackstopClient) -> tuple[ProductFetchDto, ...]:
    """Walk /products with no sparse fieldset so custom-field values arrive on each row."""
    page = await client.paginate(
        _PRODUCTS_PATH,
        schema=_ProductResource,
        max_records=None,
        page_size=_PAGE_SIZE,
    )
    return tuple(_to_dto(resource) for resource in page.items)
