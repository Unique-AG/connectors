"""List Backstop accounts for one product.

By-product listing uses `filter[product.id][eq]`. Open means the `closedDate` key is absent.

The listing asks for `fields=` and pages in parallel. `fields=` drops the whole `relationships`
block — except for the relationships named in `include=`, which keep their `data` linkage.

`closedDate` has to stay in `ACCOUNT_LISTING_FIELDS` and stay meaningful: open is *the key was
absent on the wire*, so a `fields=` set that materialized it as null would report every account
closed. It does not — of 200 rows fetched this way the key was absent on 8 and null on 0,
matching what the same accounts return unfiltered.
"""

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts.api_responses import ACCOUNT_LISTING_FIELDS, AccountApiResponse
from backstop_mcp.features.accounts.internal_dto import AccountListingDto, AccountRecordDto
from backstop_mcp.features.accounts.split_open import split_open

_ACCOUNTS_PATH = "/accounts"
_PAGE_SIZE = 100
_INCLUDE_BY_PRODUCT = "owner,investorType"


async def fetch_accounts_for_product(
    client: BackstopClient,
    *,
    product_id: str,
    include_closed: bool = False,
) -> AccountListingDto:
    page = await client.paginate(
        _ACCOUNTS_PATH,
        schema=AccountApiResponse,
        params={
            "filter[product.id][eq]": product_id,
            "include": _INCLUDE_BY_PRODUCT,
            "fields": ACCOUNT_LISTING_FIELDS,
        },
        max_records=None,
        page_size=_PAGE_SIZE,
        parallel=True,
    )
    return split_open(
        AccountRecordDto.from_resources(page.items, included=page.included),
        include_closed=include_closed,
    )
