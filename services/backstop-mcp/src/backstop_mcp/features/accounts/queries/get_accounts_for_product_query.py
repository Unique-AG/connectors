"""List Backstop accounts for one product.

`get_product_investors` is the consumer. By-product listing uses `filter[product.id][eq]`.
Open means the `closedDate` key is absent.

The listing asks for `fields=` and pages in parallel. `fields=` drops the whole `relationships`
block — except for the relationships named in `include=`, which keep their `data` linkage.

`closedDate` has to stay in `ACCOUNT_LISTING_FIELDS` and stay meaningful: open is *the key was
absent on the wire*, so a `fields=` set that materialized it as null would report every account
closed. It does not — of 200 rows fetched this way the key was absent on 8 and null on 0,
matching what the same accounts return unfiltered.
"""

from backstop_mcp.backstop_client import BackstopClient, Included
from backstop_mcp.features.accounts.api_responses import ACCOUNT_LISTING_FIELDS, AccountApiResource
from backstop_mcp.features.accounts.internal_dto import ResolvedProductDto
from backstop_mcp.features.accounts.responses import (
    AccountRowResponse,
    ProductInvestorsResolvedResponse,
    ProductRefResponse,
    closed_hint,
)


class GetAccountsForProductQuery:
    """Accounts in one product, with owners, and no figures."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self, *, product: ResolvedProductDto, include_closed: bool = False
    ) -> ProductInvestorsResolvedResponse:
        page = await self._client.paginate(
            "/accounts",
            schema=AccountApiResource,
            params={
                "filter[product.id][eq]": product.id,
                "include": "owner,investorType",
                "fields": ACCOUNT_LISTING_FIELDS,
            },
            max_records=None,
            page_size=100,
            parallel=True,
        )
        included = Included(page.included)
        rows = tuple(
            AccountRowResponse.from_resource(resource, included=included)
            for resource in page.items
        )
        kept = rows if include_closed else tuple(row for row in rows if row.is_open)
        closed_omitted = 0 if include_closed else len(rows) - len(kept)
        return ProductInvestorsResolvedResponse(
            product=ProductRefResponse.from_product(product),
            accounts=kept,
            closed_omitted=closed_omitted,
            include_closed_hint=closed_hint(
                closed_omitted=closed_omitted,
                returned=len(kept),
                subject="product",
            ),
        )
