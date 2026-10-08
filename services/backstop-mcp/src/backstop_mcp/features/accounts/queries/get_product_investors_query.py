"""Who holds a set of resolved products: one listing per product, one entry per investor.

`get_product_investors` is the consumer; it resolves the products and hands them here. Each
investor's `continuous_since` comes from every account it has had in these products, closed ones
included, so `include_closed` hides rows without shortening tenure. Latest values are fetched
only when asked, one request per account, and refused past `max_valued_accounts`.
"""

import asyncio
from collections.abc import Callable, Sequence
from datetime import date

from backstop_mcp.features.accounts.internal_dto import ResolvedProductDto, TenureDto
from backstop_mcp.features.accounts.queries.get_accounts_for_product_query import (
    GetAccountsForProductQuery,
)
from backstop_mcp.features.accounts.queries.get_latest_account_values_query import (
    GetLatestAccountValuesQuery,
)
from backstop_mcp.features.accounts.responses import (
    LatestValueResponse,
    ProductAccountsResponse,
    ProductInvestorsResolvedResponse,
    ProductListingResponse,
    investors_from_listings,
)
from backstop_mcp.features.accounts.utils import continuous_tenure


class GetProductInvestorsQuery:
    """Accounts and investors across resolved products, with tenure and optional latest values."""

    def __init__(
        self,
        *,
        get_accounts_for_product_query: GetAccountsForProductQuery,
        get_latest_account_values_query: GetLatestAccountValuesQuery,
        max_valued_accounts: int,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._get_accounts_for_product_query: GetAccountsForProductQuery = (
            get_accounts_for_product_query
        )
        self._get_latest_account_values_query: GetLatestAccountValuesQuery = (
            get_latest_account_values_query
        )
        self._max_valued_accounts: int = max_valued_accounts
        self._clock: Callable[[], date] = clock

    async def run(
        self,
        *,
        products: Sequence[ResolvedProductDto],
        include_closed: bool = False,
        include_latest_value: bool = False,
        exclude_custom_fields: bool = False,
        investor_ids: Sequence[str] = (),
    ) -> ProductInvestorsResolvedResponse:
        owner_ids = frozenset(investor_ids) if investor_ids else None
        # Each listing is its own `/accounts` walk with no ordering between products; `gather`
        # keeps the input order, so the output is the same as awaiting them one by one.
        per_product = await asyncio.gather(
            *(
                self._get_accounts_for_product_query.run(
                    product=product,
                    include_closed=include_closed,
                    exclude_custom_fields=exclude_custom_fields,
                    owner_ids=owner_ids,
                )
                for product in products
            )
        )
        listings = [accounts.listing for accounts in per_product]
        latest_value_hint: str | None = None
        if include_latest_value:
            listings, latest_value_hint = await self._with_latest_values(listings)
        return ProductInvestorsResolvedResponse(
            products=tuple(listings),
            investors=investors_from_listings(listings, tenure=self._tenure_by_owner(per_product)),
            latest_value_hint=latest_value_hint,
            investor_ids_not_found=(
                self._not_found(investor_ids, listings) if investor_ids else None
            ),
        )

    async def _with_latest_values(
        self, listings: list[ProductListingResponse]
    ) -> tuple[list[ProductListingResponse], str | None]:
        """Listings with `latest_value` on every account, or unchanged plus why over the cap."""
        account_count = sum(len(listing.accounts) for listing in listings)
        if account_count > self._max_valued_accounts:
            return listings, self._over_limit_hint(listings, account_count=account_count)
        latest = await self._get_latest_account_values_query.run(
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
        self, listings: list[ProductListingResponse], *, account_count: int
    ) -> str:
        """Why no values came back, and the narrower calls that would fit — cheapest first."""
        each_vehicle_fits = len(listings) > 1 and all(
            len(listing.accounts) <= self._max_valued_accounts for listing in listings
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
            f"No values fetched: {account_count} accounts is over the "
            f"{self._max_valued_accounts}-account limit. Narrow and call again: pass "
            "`investor_ids` with only the investors the answer needs (ids from `investors[]`); "
            f"{per_vehicle}or drop closed accounts. If none fits, tell the user and offer: "
            "get_accounts_for_party on each `investors[]` entry (`id` as `party_id`, "
            "`resource_type` as `search_type`) — one request per investor, balances carry no "
            "as-of date, and it lists the investor's other funds too, so keep only this "
            "response's `account_ids`; or, if the firm keeps a saved Report Center report of "
            "investor balances, run_report by its exact name (ask the user for it). Fund-level "
            "AUM alone is get_time_series on the product's `aums`. Do not call get_time_series "
            "on every account."
        )

    def _tenure_by_owner(
        self, per_product: Sequence[ProductAccountsResponse]
    ) -> dict[str, TenureDto]:
        """Each owner's tenure across every product in this call, closed accounts included."""
        today = self._clock()
        owner_ids = dict.fromkeys(
            owner_id for accounts in per_product for owner_id in accounts.spans_by_owner
        )
        return {
            owner_id: continuous_tenure(
                (
                    span
                    for accounts in per_product
                    for span in accounts.spans_by_owner.get(owner_id, ())
                ),
                today=today,
            )
            for owner_id in owner_ids
        }

    def _not_found(
        self, investor_ids: Sequence[str], listings: Sequence[ProductListingResponse]
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
