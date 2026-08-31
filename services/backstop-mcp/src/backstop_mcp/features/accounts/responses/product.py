"""`get_product` published shapes: one product or the catalog, with custom-field values."""

from typing import Literal

from pydantic import Field

from backstop_mcp.features.custom_fields import ResolvedCustomFieldValueResponse
from backstop_mcp.models import OmitNoneModel

# Scan ceiling for the catalog walk. 72 products on this instance; `resolve_product` already
# warns past 400 because re-reading the catalog per search stops paying for itself. This is the
# hard stop above that warning, so a tenant with a pathological catalog gets a stated prefix
# rather than an unbounded read.
MAX_PRODUCT_SCAN_RECORDS = 2_000


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
            "Matching products. One item when a name (`search` / `product`) or id was passed; "
            "the catalog when none was. The catalog is small (~72 on this instance) — this is "
            "one walk, not a per-product fan-out."
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
