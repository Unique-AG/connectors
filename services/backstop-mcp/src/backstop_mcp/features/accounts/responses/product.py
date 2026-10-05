"""`search_products` published shapes: the matching products, with custom-field values."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from backstop_mcp.features.custom_fields import ResolvedCustomFieldValueResponse
from backstop_mcp.models import OmitNoneModel

# Scan ceiling for the catalog walk. `resolve_product` already warns past 400 because re-reading
# the catalog per search stops paying for itself. This is the hard stop above that warning, so a
# tenant with a pathological catalog gets a stated prefix rather than an unbounded read.
MAX_PRODUCT_SCAN_RECORDS = 2_000


class ProductDescriptionResponse(OmitNoneModel):
    """Free-text blurbs Backstop holds on the product. Blank ones are omitted."""

    fund_description: str | None = Field(default=None, description="Fund description.")
    manager_bio: str | None = Field(default=None, description="Manager biography.")
    thesis: str | None = Field(default=None, description="Investment thesis.")
    investment_methodology: str | None = Field(default=None, description="Investment methodology.")


class ProductRiskFreeRateResponse(OmitNoneModel):
    """How the product's risk-free rate is set."""

    floating: bool | None = Field(
        default=None, description="True when the rate floats on a benchmark."
    )
    floating_rate_benchmark_symbol: str | None = Field(
        default=None,
        description="Benchmark symbol as Backstop stores it. 'None' is Backstop's own value.",
    )


class ProductRecordResponse(OmitNoneModel):
    """One product identity plus its custom-field values."""

    id: str = Field(
        description=(
            "Backstop product id. Echo it as a `products` entry on `get_product_investors`, as "
            "`entity_id` on `get_time_series` with `entity_type='products'`, or as `product_ids` "
            "on `search_products` — never invent one."
        )
    )
    name: str | None = Field(default=None, description="Product name as Backstop stores it.")
    short_name: str | None = Field(
        default=None,
        description="`productShortName` (e.g. 'NGUP'). Tenants may call this a fund or vehicle.",
    )
    product_type: str | None = Field(
        default=None,
        description=(
            "Backstop `productType`, e.g. 'ONSHORE_BALANCE_DRIVEN_TMV'. The `product_type` "
            "filter on `search_products` matches this value whole, case-insensitively."
        ),
    )
    is_onshore: bool | None = Field(
        default=None, description="Backstop `isOnshore` flag: true or false."
    )
    inception_date: date | None = Field(default=None, description="Product inception date.")
    currency: str | None = Field(
        default=None, description="Default product currency (ISO code), e.g. 'USD'."
    )
    master_product_name: str | None = Field(
        default=None, description="`masterProductName` the product rolls up under."
    )
    fiscal_year_start_month: int | None = Field(
        default=None, description="Fiscal year start month, 1-12."
    )
    return_calculation_methodology: str | None = Field(
        default=None, description="Backstop `returnCalculationMethodology`, e.g. 'TWRR_MV_MR'."
    )
    modified_timestamp: datetime | None = Field(
        default=None,
        description="Last modification time. `modified_since` on `search_products` filters on it.",
    )
    city: str | None = Field(default=None, description="Product location city.")
    state_or_province: str | None = Field(default=None, description="Product location state.")
    country: str | None = Field(default=None, description="Product location country.")
    description: ProductDescriptionResponse | None = Field(
        default=None,
        description="Free-text blurbs on the product. Omitted when all four are blank.",
    )
    risk_free_rate: ProductRiskFreeRateResponse | None = Field(
        default=None, description="Risk-free rate setup. Omitted when Backstop sends none."
    )
    service_providers: dict[str, str] | None = Field(
        default=None,
        description=(
            "Service providers by Backstop's role key (e.g. `administrator`, `auditors`, "
            "`custodian`, `primeBroker`), value the provider's name as typed. Only roles "
            "with a name; omitted when there are none."
        ),
    )
    custom_field_values: list[ResolvedCustomFieldValueResponse] = Field(
        default_factory=list,
        description=(
            "Custom-field values on this product joined to list_custom_fields definitions "
            "(every product custom field with a value). Empty when the record has none or the "
            "catalog could not be loaded. Slice with custom_field_names rather than fetching again."
        ),
    )
    url: str | None = Field(
        default=None,
        description=(
            "Canonical CRM UI URL for this product (no tab). Omitted when this deployment "
            "has no UI origin. Echo it; never invent one. Call build_backstop_links for "
            "tabs or a layout."
        ),
    )


class ProductResolvedResponse(OmitNoneModel):
    """`search_products` once products were read, filtered, and custom fields joined."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the search ran. An empty `products` is 'no match'.",
    )
    products: tuple[ProductRecordResponse, ...] = Field(
        description=(
            "Every product that satisfies all the filters passed, sorted by name; the whole "
            "catalog when none was. Zero, one, or many. Several is not an error and nothing "
            "here picks one for the user."
        )
    )
    scan_truncated: bool = Field(
        default=False,
        description=(
            f"True when the catalog walk stopped at the {MAX_PRODUCT_SCAN_RECORDS}-product scan "
            "ceiling, so `products` is a prefix of the matches. An absent product then means "
            "'not in what was read', not 'not in the firm'."
        ),
    )
