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
from backstop_mcp.config import ProductInvestorsConfig
from backstop_mcp.dependencies import (
    get_backstop_client_for_current_caller,
    get_product_investors_config,
)
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
                "closed accounts."
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
    get_accounts_for_product_query: GetAccountsForProductQuery = Depends(
        get_accounts_for_product_query_factory
    ),
    get_latest_account_values_query: GetLatestAccountValuesQuery = Depends(
        get_latest_account_values_query_factory
    ),
    config: ProductInvestorsConfig = Depends(get_product_investors_config),
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
        owner_ids = frozenset(requested_investors) if requested_investors else None
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
        listings: list[ProductListingResponse] = []
        for resolved in resolved_products:
            listings.append(
                await get_accounts_for_product_query.run(
                    product=resolved,
                    include_closed=include_closed,
                    exclude_custom_fields=exclude_custom_fields,
                    owner_ids=owner_ids,
                )
            )
        latest_value_hint: str | None = None
        if include_latest_value:
            listings, latest_value_hint = await _with_latest_values(
                listings,
                get_latest_account_values_query,
                max_valued_accounts=config.max_valued_accounts,
            )
        investors = investors_from_listings(listings)
        result = ProductInvestorsResolvedResponse(
            products=tuple(listings),
            investors=investors,
            latest_value_hint=latest_value_hint,
            investor_ids_not_found=(
                _not_found(requested_investors, listings) if requested_investors else None
            ),
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
    *,
    max_valued_accounts: int,
) -> tuple[list[ProductListingResponse], str | None]:
    """Listings with `latest_value` on every account, or unchanged plus why when over the cap."""
    account_count = sum(len(listing.accounts) for listing in listings)
    if account_count > max_valued_accounts:
        return listings, _over_limit_hint(
            listings, account_count=account_count, max_valued_accounts=max_valued_accounts
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


def _over_limit_hint(
    listings: list[ProductListingResponse], *, account_count: int, max_valued_accounts: int
) -> str:
    """Why no values came back, and the narrower calls that would fit — cheapest first."""
    each_vehicle_fits = len(listings) > 1 and all(
        len(listing.accounts) <= max_valued_accounts for listing in listings
    )
    per_vehicle = (
        (
            "or call once per vehicle (each fits the limit) and add "
            "`investors[].latest_value_totals` up by investor `id`; "
        )
        if each_vehicle_fits
        else ""
    )
    return (
        f"No values fetched: {account_count} accounts is over the {max_valued_accounts}-account "
        "limit. Narrow and call again: pass `investor_ids` with only the investors the answer "
        f"needs (ids from `investors[]`); {per_vehicle}or drop closed accounts. If none fits, "
        "tell the user and offer: get_accounts_for_party on each `investors[]` entry (`id` as "
        "`party_id`, `resource_type` as `search_type`) — one request per investor, balances "
        "carry no as-of date, and it lists the investor's other funds too, so keep only this "
        "response's `account_ids`; or, if the firm keeps a saved Report Center report of "
        "investor balances, run_report by its exact name (ask the user for it). Fund-level AUM "
        "alone is get_time_series on the product's `aums`. Do not call get_time_series on every "
        "account."
    )


def _not_found(
    investor_ids: Sequence[str], listings: Sequence[ProductListingResponse]
) -> tuple[str, ...]:
    """Requested ids with no listed account, in the order given, each once."""
    listed = {
        candidate
        for listing in listings
        for account in listing.accounts
        if account.owner is not None
        for candidate in (account.owner.id, account.owner.contacts_id)
        if candidate is not None
    }
    return tuple(dict.fromkeys(entry for entry in investor_ids if entry not in listed))
