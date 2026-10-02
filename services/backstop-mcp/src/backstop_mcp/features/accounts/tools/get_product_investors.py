"""Who holds one or more products, and each account's latest value only when asked.

Values are one request per account and capped. Any other dated figure is `get_time_series`.
"""

import logging
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
    GetAccountsForProductQuery,
    GetLatestAccountValuesQuery,
    ProductAmbiguousResponse,
    ProductInvestorsResolvedResponse,
    ResolvedProductDto,
    resolve_product_family,
)
from backstop_mcp.features.accounts.dependencies import (
    get_accounts_for_product_query_factory,
    get_latest_account_values_query_factory,
)
from backstop_mcp.features.accounts.responses import (
    LatestValueResponse,
    ProductListingResponse,
    investors_from_listings,
)
from backstop_mcp.features.resolution import NotFoundResponse, input_required
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

type GetProductInvestorsResponse = (
    ProductAmbiguousResponse | NotFoundResponse | ProductInvestorsResolvedResponse
)

_MAX_PRODUCTS = 10

# Both vehicles of a fund with ~25 open accounts fit comfortably. Past this the answer is slow
# enough that the user should narrow the scope rather than wait.
_MAX_VALUED_ACCOUNTS = 50


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
                "or names. A name covers every vehicle it matches (onshore and offshore) — "
                "`['Northwind Dispersion Fund']` returns both feeders. An exact short name or id "
                "is exactly that one vehicle; pass several (`['NWON', 'NWOF']`) when the user "
                "names specific ones. Never invent an id."
            ),
        ),
    ],
    include_closed: Annotated[
        bool,
        Field(
            description=(
                "When false (default), only open accounts are returned (`closedDate` key "
                "absent). Pass true to include closed accounts."
            ),
        ),
    ] = False,
    include_latest_value: Annotated[
        bool,
        Field(
            description=(
                "Adds each account's latest value (amount, currency, as-of date, ACTUAL or "
                "ESTIMATE) and per-owner totals — the answer to 'list investors by size'. It "
                "costs one Backstop request per account and is refused past "
                f"{_MAX_VALUED_ACCOUNTS} accounts. **Ask the user first**: list the vehicles "
                "you resolved and whether closed accounts count, and get a yes before passing "
                "true. Do not turn it on just because the question mentions size or balance. "
                "For a specific date or any other series, use get_time_series instead."
            ),
        ),
    ] = False,
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    get_accounts_for_product_query: GetAccountsForProductQuery = Depends(
        get_accounts_for_product_query_factory
    ),
    get_latest_account_values_query: GetLatestAccountValuesQuery = Depends(
        get_latest_account_values_query_factory
    ),
) -> GetProductInvestorsResponse | InputRequiredResult:
    """The accounts in one or more products, and who owns them.

    A fund name covers every vehicle it matches (onshore and offshore); an exact short name is
    one vehicle. No figures by default.

    Sizing ("list investors by size", "biggest holders"): first call without figures, tell
    the user which vehicles and how many accounts you found, and ask whether to pull latest
    values. Only after they confirm, call again with `include_latest_value=true` and rank by
    `investors[].latest_value_totals`. Never call `get_time_series` once per account in the
    fund — that is one call per (account, series), reconstitutes the fan-out this connector
    removed, and drops rows. Fund-level AUM is `get_time_series` on a product's `aums`, which
    is the product's total assets under management, not one investor's balance.

    `products` has one listing per vehicle with its accounts. `investors` has one entry per
    owner across every vehicle, with a holding per vehicle they are in. Investor
    `resource_type` may be `contacts` even when the party is an organization — echo `id` and
    `resource_type` together as a later party resolve; do not assume `contacts` means a
    person. A listing with no accounts and `closed_omitted>0` means every account in that
    product is closed — pass `include_closed=true` rather than reading that as "no investors".

    Call like: {"products": ["NGUP"], "include_latest_value": false}
    """
    with _tracer.start_as_current_span("accounts.product_investors") as span:
        span.set_attribute("product_count", len(products))
        span.set_attribute("include_closed", include_closed)
        span.set_attribute("include_latest_value", include_latest_value)
        resolved_products = await _resolve_products(ctx, client, products=products)
        if not isinstance(resolved_products, tuple):
            return resolved_products

        logger.info(
            "accounts.product_investors.start",
            extra={
                "product_ids": [item.id for item in resolved_products],
                "include_closed": include_closed,
                "include_latest_value": include_latest_value,
            },
        )
        listings: list[ProductListingResponse] = []
        for resolved in resolved_products:
            listings.append(
                await get_accounts_for_product_query.run(
                    product=resolved, include_closed=include_closed
                )
            )
        latest_value_hint: str | None = None
        if include_latest_value:
            listings, latest_value_hint = await _with_latest_values(
                listings, get_latest_account_values_query
            )
        result = ProductInvestorsResolvedResponse(
            products=tuple(listings),
            investors=investors_from_listings(listings),
            latest_value_hint=latest_value_hint,
        )
        accounts = [account for listing in listings for account in listing.accounts]
        logger.info(
            "accounts.product_investors.completed",
            extra={
                "product_ids": [listing.product.id for listing in listings],
                "returned": len(accounts),
                "closed_omitted": sum(listing.closed_omitted for listing in listings),
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
    """Every entry through the family resolve, deduped by product id in the order given."""
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


async def _with_latest_values(
    listings: list[ProductListingResponse],
    get_latest_account_values_query: GetLatestAccountValuesQuery,
) -> tuple[list[ProductListingResponse], str | None]:
    """Listings with `latest_value` on every account, or unchanged plus why when over the cap."""
    account_count = sum(len(listing.accounts) for listing in listings)
    if account_count > _MAX_VALUED_ACCOUNTS:
        return listings, (
            f"No values fetched: {account_count} accounts is over the "
            f"{_MAX_VALUED_ACCOUNTS}-account limit. Tell the user and offer one of: narrow "
            "the scope (fewer vehicles, or open accounts only) and call again; size by investor "
            "with get_accounts_for_party on each `investors[]` entry (`id` as `party_id`, "
            "`resource_type` as `search_type`) — one request per investor, balances carry no "
            "as-of date, and it lists the investor's other funds too, so keep only this "
            "response's `account_ids`; or, if the firm keeps a saved Report Center report of "
            "investor balances, run_report by its exact name (ask the user for it). Fund-level "
            "AUM alone is get_time_series on the product's `aums`. Do not call get_time_series "
            "on every account."
        )
    latest = await get_latest_account_values_query.run(
        account_ids=[account.id for listing in listings for account in listing.accounts]
    )
    by_account = {value.account_id: value for value in latest}
    return [
        listing.model_copy(
            update={
                "accounts": tuple(
                    account.model_copy(
                        update={
                            "latest_value": LatestValueResponse.from_dto(
                                by_account[account.id], currency=account.currency
                            )
                        }
                    )
                    for account in listing.accounts
                )
            }
        )
        for listing in listings
    ], None
