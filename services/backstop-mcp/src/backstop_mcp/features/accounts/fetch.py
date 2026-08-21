"""List Backstop accounts by product or by owning party.

`filter[owner]` / `filter[owner.id]` are 400 (the `/accounts` filter enum is `createdTimestamp,
modifiedTimestamp, name, otherId, product.*` only), and neither `/people/{id}` nor
`/organizations/{id}` exposes an `accounts` subcollection. By-product listing uses
`filter[product.id][eq]`. By-party listing therefore walks the whole of `/accounts` and keeps
rows the party owns: the `relationships.owner` linkage id first, since that needs no side-load,
then the projected owner id, which is `specificResource.resourceId` for an organization owner.
Matching only the linkage would drop exactly the rows whose owner id the tool goes on to echo.
Open means the `closedDate` key is absent.

Both listings ask for `fields=` and page in parallel, which together is what makes the by-party
walk affordable: unfiltered, an `accounts` resource is ~9.6 KiB, ~90% of it the `links` boilerplate
of 30 relationships nothing here reads. `fields=` drops the whole `relationships` block — except
for the relationships named in `include=`, which keep their `data` linkage, so `_owns` still sees
the `owner` pointer. Measured over this instance's 815 accounts: 97.1s/13.1 MiB unchanged,
17.2s/4.5 MiB with `fields=` alone, 31.7s with parallel paging alone, 9.1s/4.3 MiB with both.

`closedDate` has to stay in `_FIELDS` and stay meaningful: open is *the key was absent on the
wire*, so a `fields=` set that materialized it as null would report every account closed. It does
not — of 200 rows fetched this way the key was absent on 8 and null on 0, matching what the same
accounts return unfiltered.
"""

from collections.abc import Sequence

from backstop_mcp.backstop_client import BackstopClient, follow_included
from backstop_mcp.features.accounts.api_responses import AccountApiResponse
from backstop_mcp.features.accounts.internal_dto import (
    AccountListingDto,
    AccountOwnerDto,
    AccountRecordDto,
)
from backstop_mcp.features.accounts.split_open import split_open

_ACCOUNTS_PATH = "/accounts"
_PAGE_SIZE = 100
_INCLUDE_BY_PRODUCT = "owner,investorType"
_INCLUDE_BY_PARTY = "owner,investorType,product"
_OWNER = "owner"

# Exactly the attributes `AccountAttributes` reads, by wire name. Anything added there has to be
# added here too, or it arrives as `None` on every row instead of failing loudly.
_FIELDS = ",".join(
    (
        "name",
        "currency",
        "accountStartDate",
        "closedDate",
        "ownershipType",
        "investorQualification",
        "isEmployeeAccount",
        "isGpAccount",
        "amlCheckComplete",
        "newIssueEligible",
        "usDomiciled",
    )
)


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
            "fields": _FIELDS,
        },
        max_records=None,
        page_size=_PAGE_SIZE,
        parallel=True,
    )
    return split_open(
        AccountRecordDto.from_resources(page.items, included=page.included),
        include_closed=include_closed,
    )


async def fetch_accounts_for_party(
    client: BackstopClient,
    *,
    owner_id: str,
    include_closed: bool = False,
) -> AccountListingDto:
    page = await client.paginate(
        _ACCOUNTS_PATH,
        schema=AccountApiResponse,
        params={"include": _INCLUDE_BY_PARTY, "fields": _FIELDS},
        max_records=None,
        page_size=_PAGE_SIZE,
        parallel=True,
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
) -> tuple[AccountRecordDto, ...]:
    return tuple(
        AccountRecordDto.from_resource(resource, included=included)
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
    related = follow_included(included, resource, _OWNER)
    owner = AccountOwnerDto.from_included(related[0] if related else None)
    return owner is not None and owner.id == owner_id
