"""List Backstop accounts by product or by owning party.

`filter[owner]` / `filter[owner.id]` are 400, and organizations have no `/accounts` subcollection.
By-product listing uses `filter[product.id][eq]`. By-party listing walks `/accounts` and keeps
rows the party owns: the `relationships.owner` linkage id first, since that needs no side-load,
then the projected owner id, which is `specificResource.resourceId` for an organization owner.
Matching only the linkage would drop exactly the rows whose owner id the tool goes on to echo.
Open means the `closedDate` key is absent.
"""

from collections.abc import Sequence

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts.project import (
    AccountApiResponse,
    account_owner,
    project_account,
    project_accounts,
    split_open,
)
from backstop_mcp.features.accounts.types import AccountListing, AccountRecord

_ACCOUNTS_PATH = "/accounts"
_PAGE_SIZE = 100
_INCLUDE_BY_PRODUCT = "owner,investorType"
_INCLUDE_BY_PARTY = "owner,investorType,product"
_OWNER = "owner"


async def fetch_accounts_for_product(
    client: BackstopClient,
    *,
    product_id: str,
    include_closed: bool = False,
) -> AccountListing:
    page = await client.paginate(
        _ACCOUNTS_PATH,
        schema=AccountApiResponse,
        params={
            "filter[product.id][eq]": product_id,
            "include": _INCLUDE_BY_PRODUCT,
        },
        max_records=None,
        page_size=_PAGE_SIZE,
    )
    return split_open(
        project_accounts(page.items, included=page.included),
        include_closed=include_closed,
    )


async def fetch_accounts_for_party(
    client: BackstopClient,
    *,
    owner_id: str,
    include_closed: bool = False,
) -> AccountListing:
    page = await client.paginate(
        _ACCOUNTS_PATH,
        schema=AccountApiResponse,
        params={"include": _INCLUDE_BY_PARTY},
        max_records=None,
        page_size=_PAGE_SIZE,
    )
    return split_open(
        _owned_accounts(page.items, included=page.included, owner_id=owner_id),
        include_closed=include_closed,
    )


def _owned_accounts(
    resources: Sequence[AccountApiResponse],
    *,
    included: Sequence[dict[str, object]],
    owner_id: str,
) -> tuple[AccountRecord, ...]:
    return tuple(
        project_account(resource, included=included)
        for resource in resources
        if _owns(resource, included=included, owner_id=owner_id)
    )


def _owns(
    resource: AccountApiResponse,
    *,
    included: Sequence[dict[str, object]],
    owner_id: str,
) -> bool:
    """Linkage id first — it costs nothing and works without the `owner` include."""
    if owner_id in resource.related_ids(_OWNER):
        return True
    owner = account_owner(resource, included=included)
    return owner is not None and owner.id == owner_id
