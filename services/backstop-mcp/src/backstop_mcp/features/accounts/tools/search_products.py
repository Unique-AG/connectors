"""`search_products`: every product that matches the filters, with custom-field values.

`name` and `modified_since` are sent to Backstop. `product_ids`, `product_type`, `is_onshore`,
and `custom_fields` are applied after the read: those are 400 on `GET /products`. Product custom
fields live here — not on get_product_investors (owners only) and not on list_custom_fields
(definitions only).
"""

import asyncio
from collections.abc import Sequence
from datetime import date
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backstop_mcp.features.accounts import (
    ProductDescriptionResponse,
    ProductFetchDto,
    ProductRecordResponse,
    ProductResolvedResponse,
    ProductRiskFreeRateResponse,
    SearchProductsQuery,
    search_products_query_factory,
)
from backstop_mcp.features.custom_fields import (
    CustomFieldFilters,
    CustomFieldMatch,
    CustomFieldsService,
    get_custom_fields_service,
)
from backstop_mcp.features.ui_links import (
    BuildEntityLinkUtil,
    ProductLinkTarget,
    get_build_entity_link_util_factory,
)
from backstop_mcp.models import CoercedId, NonEmptyStr, coerce_ids, published_output_schema


class ProductCustomFieldFilter(BaseModel):
    """One custom-field predicate. Several predicates AND together."""

    definition_id: CoercedId = Field(
        description=(
            "Custom-field definition id from list_custom_fields. Not the field label: "
            "two definitions can share a name."
        )
    )
    values: list[NonEmptyStr] = Field(
        min_length=1,
        description=(
            "Stored values that satisfy this predicate, OR. Each is compared whole and "
            "case-insensitively against the select options list_custom_fields returns — "
            "pass every option that counts, not a substring. Near-duplicate options are "
            "different values: pass both. "
            "A missing value does not match — this filter cannot mean 'the field is empty'."
        ),
    )


async def _record(
    custom_fields: CustomFieldsService,
    fetched: ProductFetchDto,
    *,
    names: Sequence[str],
    url: str | None,
) -> ProductRecordResponse:
    values = await custom_fields.join_values(
        fetched.stored_custom_field_values,
        filters=CustomFieldFilters(names=tuple(names)),
    )
    return ProductRecordResponse(
        id=fetched.product.id,
        name=fetched.product.name,
        short_name=fetched.product.short_name,
        product_type=fetched.product_type,
        is_onshore=fetched.is_onshore,
        inception_date=fetched.inception_date,
        currency=fetched.currency,
        master_product_name=fetched.master_product_name,
        fiscal_year_start_month=fetched.fiscal_year_start_month,
        return_calculation_methodology=fetched.return_calculation_methodology,
        modified_timestamp=fetched.modified_timestamp,
        city=fetched.city,
        state_or_province=fetched.state_or_province,
        country=fetched.country,
        description=(
            None
            if fetched.description is None
            else ProductDescriptionResponse.model_validate(
                fetched.description, from_attributes=True
            )
        ),
        risk_free_rate=(
            None
            if fetched.risk_free_rate is None
            else ProductRiskFreeRateResponse.model_validate(
                fetched.risk_free_rate, from_attributes=True
            )
        ),
        service_providers=fetched.service_providers or None,
        custom_field_values=values,
        url=url,
    )


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(ProductResolvedResponse),
)
async def search_products(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Case-insensitive substring of the product name: 'Global' finds 'Acme "
                "Global Fund'. If no product name contains it, it is tried once as a whole "
                "short name ('NGUP', case-insensitive). A fragment of a short name finds "
                "nothing. Sent to Backstop."
            ),
        ),
    ] = None,
    product_ids: Annotated[
        Sequence[CoercedId],
        Field(
            description=(
                "Product ids from an earlier result — never invent one. Several are OR: a "
                "product with any of these ids passes. AND with every other filter, so "
                "`product_ids` with `name` returns only those ids whose name also matches. "
                "Ids with no product are absent from the result, not an error. Applied "
                "after the read."
            ),
        ),
    ] = (),
    modified_since: Annotated[
        date | None,
        Field(
            description=("Only products modified after this date (YYYY-MM-DD). Sent to Backstop."),
        ),
    ] = None,
    product_type: Annotated[
        str | None,
        Field(
            description=(
                "Backstop `productType`, matched whole and case-insensitively, e.g. "
                "'ONSHORE_BALANCE_DRIVEN_TMV'. Use a `product_type` value from an earlier "
                "result. One value; for several, make one call each. Applied after the read."
            ),
        ),
    ] = None,
    is_onshore: Annotated[
        bool | None,
        Field(
            description=(
                "Only products whose Backstop `isOnshore` flag equals this: true or false. "
                "Omit for both. Applied after the read."
            ),
        ),
    ] = None,
    custom_fields: Annotated[
        list[ProductCustomFieldFilter] | None,
        Field(
            description=(
                "Custom-field predicates, AND between predicates. Within one predicate any "
                "listed value is enough (OR). Get definition ids and the allowed values from "
                "list_custom_fields; list every option that counts. Applied after the read."
            ),
        ),
    ] = None,
    custom_field_names: Annotated[
        Sequence[str],
        Field(
            description=(
                "Which custom-field values to return on each product, by name, e.g. "
                '"<name from list_custom_fields>". Case-insensitive. Omit to keep every '
                "name. This only trims the output; it never filters products — use "
                "`custom_fields` for that."
            ),
        ),
    ] = (),
    custom_fields_service: CustomFieldsService = Depends(get_custom_fields_service),
    search_products_query: SearchProductsQuery = Depends(search_products_query_factory),
    build_entity_link_util: BuildEntityLinkUtil = Depends(get_build_entity_link_util_factory),
) -> ProductResolvedResponse:
    """Find products (funds, vehicles) and read their custom-field values. Returns every match.

    How filters combine: every filter you pass must hold (AND). Inside one filter that takes
    several values (`product_ids`, one custom-field predicate's `values`) any one value is
    enough (OR). A filter you omit narrows nothing; with no filters this reads the whole
    catalog in one call, sorted by name.

    This tool never picks a product for the user. Zero rows means nothing matched: say so
    rather than guessing a looser name. Several rows that are vehicles of one fund (the
    same fund in other domiciles or share classes) are that fund: use them together unless the user
    named one vehicle. Several rows that are different funds when the user named one: list
    them (name, short name, type) and ask which they want — one, some, or all — before you
    call another tool. Do not take the first row. When the user asked for a group ("every
    product of type X"), several rows are the answer.

    Next steps: pass the ids of the chosen products to get_product_investors (who holds
    them) or one at a time to get_time_series. Do not iterate those tools over the catalog
    to find a product attribute: product type, the `isOnshore` flag, inception date, and
    product custom fields are all returned or filtered here.
    """
    # Overlap the product read with a schema-cache warm. Each row then joins against a filled
    # catalog; the load return is unused because `_record` reads the cache.
    fetched, _ = await asyncio.gather(
        search_products_query.run(
            name=name,
            modified_since=modified_since,
            product_ids=coerce_ids(product_ids),
            product_type=product_type,
            is_onshore=is_onshore,
            custom_fields=tuple(
                CustomFieldMatch(definition_id=item.definition_id, values=tuple(item.values))
                for item in custom_fields or ()
            ),
        ),
        custom_fields_service.load_catalog(),
    )
    # Concurrently: each row is a catalog join with no ordering between rows, so a sequential
    # comprehension would await them one by one for nothing.
    products = await asyncio.gather(
        *(
            _record(
                custom_fields_service,
                item,
                names=custom_field_names,
                url=build_entity_link_util.canonical_url(
                    target=ProductLinkTarget(entity_id=item.product.id)
                ),
            )
            for item in fetched.products
        )
    )
    return ProductResolvedResponse(products=tuple(products))
