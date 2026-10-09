"""Who holds one or more products, and each account's latest value only when asked.

One listing per product plus one entry per investor across them. No figures by default;
`include_latest_value=true` adds each account's latest `values` point and per-investor totals,
one request per account, capped at `_MAX_VALUED_ACCOUNTS` — so the model never loops
`get_time_series` over a fund's accounts.
"""

import logging
from collections.abc import Sequence
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import InputRequiredResult, ToolAnnotations
from opentelemetry import trace
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.accounts import (
    GetProductInvestorsQuery,
    ProductAmbiguousResponse,
    ProductInvestorsResolvedResponse,
    ResolvedProductDto,
    resolve_product_family,
)
from backstop_mcp.features.accounts.dependencies import get_product_investors_query_factory
from backstop_mcp.features.resolution import NotFoundResponse, input_required
from backstop_mcp.models import CoercedId, coerce_ids, published_output_schema

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

type GetProductInvestorsResponse = (
    ProductAmbiguousResponse | NotFoundResponse | ProductInvestorsResolvedResponse
)

_MAX_PRODUCTS = 10


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetProductInvestorsResponse),
)
async def get_product_investors(
    ctx: Context,
    products: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=_MAX_PRODUCTS,
            description=(
                "One to ten products: ids echoed from a prior response, short names (`NWON`), "
                "or names. An id, exact short name, or exact name is that one vehicle. A partial "
                "name returns every vehicle whose name contains it, up to 6 (several vehicles "
                "sharing a name). More matches ask the user. Pass several (`['NWON', 'NWOF']`) "
                "when the user names specific ones. "
                "Never invent an id."
            ),
        ),
    ],
    include_closed: Annotated[
        bool,
        Field(
            description=(
                "When false (default), only open accounts are returned. Pass true to include "
                "closed account rows. Investors whose accounts are all closed, and their "
                "`tenure_runs`, are in `investors` either way; only the rows are omitted."
            ),
        ),
    ] = False,
    include_latest_value: Annotated[
        bool,
        Field(
            description=(
                "Adds each account's latest value (amount, currency, as-of date, ACTUAL or "
                "ESTIMATE) and per-owner totals — the answer to 'list investors by size'. It "
                "costs one Backstop request per account and is refused past this deployment's "
                "account limit. Pass true when the answer needs balances: "
                "sizing, a share of assets, or a breakdown weighted by value. Past the limit "
                "no values are fetched and `latest_value_hint` says how to narrow. Leave it "
                "false for a list of who holds the product. For a specific date or any other "
                "series, use get_time_series instead."
            ),
        ),
    ] = False,
    investor_ids: Annotated[
        Sequence[CoercedId],
        Field(
            description=(
                "Only these investors' accounts are listed and valued: party ids from an "
                "earlier result (`investors[].id`, an activity's `associated_with`, a deal's "
                "`investor`). Pass it when the answer is about investors you already have, so "
                "the values stay under the account limit. Ids with no account here come back "
                "in `investor_ids_not_found`. Omit for everyone in the products."
            ),
        ),
    ] = (),
    exclude_custom_fields: Annotated[
        bool,
        Field(
            description=(
                "Every account's custom fields come back as `custom_field_values` by "
                "default. Leave this false. Set it true only to retry a call that timed "
                "out, to see whether reading the custom fields is what made it slow."
            )
        ),
    ] = False,
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    get_product_investors_query: GetProductInvestorsQuery = Depends(
        get_product_investors_query_factory
    ),
) -> GetProductInvestorsResponse | InputRequiredResult:
    """The accounts in one or more products, and who owns them.

    A partial fund name returns every vehicle whose name contains it; an
    id, exact short name, or exact name is one vehicle. No figures by default.

    Sizing ("list investors by size", "biggest holders", a share or breakdown by value):
    call with `include_latest_value=true` and rank by `investors[].latest_value_totals`;
    say which vehicles and whether closed accounts counted. When the investors are already
    known (from activities or a pipeline walk), pass them as `investor_ids` so only their
    accounts are valued. Past the account limit no values come back and
    `latest_value_hint` says how to narrow. Never call `get_time_series`
    once per account in the fund — that is one call per (account, series) and drops rows.
    Fund-level AUM is `get_time_series` on a product's `aums`: the product's total assets
    under management, not one investor's balance.

    Tenure (how long an investor has held these products): `investors[].tenure_runs` is every
    unbroken stretch the investor held them, closed accounts included, longest first, each with
    `years`. A run with no `end`, or an `end` after today, is held today. Investors who have left
    are listed too, with `has_open_account: false`; their closed rows need `include_closed=true`.
    Read tenure from the runs, not an account's `account_start_date`: investors who rotate
    accounts (private banks, platforms, nominees) have no single old account. It covers only the
    products passed.

    `products` has one listing per vehicle with its accounts. `investors` has one entry per
    owner across every vehicle, with a holding per vehicle they are in. Investor
    `resource_type` may be `contacts` even when the party is an organization — echo `id` and
    `resource_type` together as a later party resolve; do not assume `contacts` means a
    person. A listing with no accounts and `closed_omitted>0` means every account in that
    product is closed — pass `include_closed=true` rather than reading that as "no investors".

    Call like: {"products": ["NGUP"], "include_latest_value": false}
    Several vehicles: {"products": ["NWON", "NWOF"]}
    """
    with _tracer.start_as_current_span("accounts.product_investors") as span:
        span.set_attribute("product_count", len(products))
        span.set_attribute("include_closed", include_closed)
        span.set_attribute("include_latest_value", include_latest_value)
        span.set_attribute("exclude_custom_fields", exclude_custom_fields)
        requested_investors = coerce_ids(investor_ids)
        span.set_attribute("investor_id_count", len(requested_investors))
        resolved_products = await _resolve_products(ctx, client, products=products)
        if not isinstance(resolved_products, tuple):
            return resolved_products

        logger.info(
            "accounts.product_investors.start",
            extra={
                "product_ids": [item.id for item in resolved_products],
                "include_closed": include_closed,
                "include_latest_value": include_latest_value,
                "exclude_custom_fields": exclude_custom_fields,
                "investor_id_count": len(requested_investors),
            },
        )
        result = await get_product_investors_query.run(
            products=resolved_products,
            include_closed=include_closed,
            include_latest_value=include_latest_value,
            exclude_custom_fields=exclude_custom_fields,
            investor_ids=requested_investors,
        )
        accounts = [account for listing in result.products for account in listing.accounts]
        logger.info(
            "accounts.product_investors.completed",
            extra={
                "product_ids": [listing.product.id for listing in result.products],
                "returned": len(accounts),
                "closed_omitted": sum(listing.closed_omitted for listing in result.products),
                "valued": sum(
                    1
                    for account in accounts
                    if account.latest_value is not None and account.latest_value.available
                ),
            },
        )
        return result


async def _resolve_products(
    ctx: Context, client: BackstopClient, *, products: list[str]
) -> (
    tuple[ResolvedProductDto, ...]
    | ProductAmbiguousResponse
    | NotFoundResponse
    | InputRequiredResult
):
    """Every entry through the family resolve, deduped by product id in the order given.

    Sequential on purpose: an ambiguous entry elicits the user, and two prompts at once would
    race for the same conversation.
    """
    collected: dict[str, ResolvedProductDto] = {}
    for entry in products:
        family = await resolve_product_family(ctx, client, product=entry)
        if input_required(family):
            return family
        if not isinstance(family, tuple):
            return ProductAmbiguousResponse.from_unresolved(family)
        for product in family:
            collected.setdefault(product.id, product)
    return tuple(collected.values())
