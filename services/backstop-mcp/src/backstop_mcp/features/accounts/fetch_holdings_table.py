"""One party's holdings, with balances, from Backstop's undocumented UI table endpoint.

`GET /bsg-account-table-data?entityId={partyId}` is what the Backstop web app's account table
calls. It is not in the swagger, and it is the only single-request source of a party's accounts
*with figures* — the documented alternative is a whole-collection `/accounts` walk plus one series
request per account per figure.

Measured against a live instance, and the reasons this does not go through `paginate`:

- Rows sit at `data[0].attributes.accounts`. The `data` element's `id` is `null`, `links` is
  `null`, `included` is always `[]`, and `meta.totalResourceCount` is `0` no matter how many rows
  came back — none of the JSON:API envelope carries meaning, so `AccountTableDataDocument` models
  the body directly.
- **Paging params are ignored.** `page[limit]=2` still returned all 12 rows. The whole table
  arrives in one unbounded payload; there is nothing to page and no way to bound it.
- **Row order is not stable** across hosts, and there is no `sort` param. Order carries no
  meaning, so callers must sort in the projection rather than trusting position.
- **`entityId` is polymorphic** — an organization id and a person id both work, and the row's
  `investor.resourceType` says which came back.
- **It is investor-keyed only.** A product id returns `200` with an empty table, so this cannot
  answer "who is in this fund"; that is `fetch_accounts_for_product`.
- **It fails open.** A nonexistent id and a wrong-typed id both return `200` with
  `accounts: []` and no `errors`, indistinguishable from a party that owns nothing. So an empty
  table is only trustworthy when `entity_id` came from `resolve_party`, which is why this function
  takes a resolved id and never a caller-supplied string.

`balance` here carries no as-of date and no `valueStatus`, though it matched the newest
`/accounts/{id}/values` point exactly on a measured account — including when that point was an
`ESTIMATE`. A dated, labelled figure needs the series endpoint.
"""

import logging

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts.api_responses import AccountTableDataDocument
from backstop_mcp.features.accounts.internal_dto import HoldingListingDto, HoldingRowDto

logger = logging.getLogger(__name__)

_TABLE_DATA_PATH = "/bsg-account-table-data"
_ENTITY_ID = "entityId"


async def fetch_holdings_table(
    client: BackstopClient,
    *,
    entity_id: str,
    include_closed: bool = False,
) -> HoldingListingDto:
    """A party's accounts with snapshot figures, in one request.

    `entity_id` must be a resolved party id (see the fail-open note above). Raises whatever
    `BackstopClient` raises — the caller decides whether to fall back to the documented walk.
    """
    document = await client.get(
        _TABLE_DATA_PATH,
        schema=AccountTableDataDocument,
        params={_ENTITY_ID: entity_id},
    )
    table = document.table
    projected = tuple(HoldingRowDto.from_attributes(row) for row in table.accounts)
    rows = tuple(row for row in projected if row is not None)
    rows_dropped = len(projected) - len(rows)
    if rows_dropped:
        logger.warning(
            "accounts.holdings_table.rows_without_account_id",
            extra={"entity_id": entity_id, "dropped": rows_dropped, "returned": len(projected)},
        )
    kept = rows if include_closed else tuple(row for row in rows if not row.closed)
    logger.info(
        "accounts.holdings_table.fetched",
        extra={
            "entity_id": entity_id,
            "rows": len(kept),
            "closed_omitted": len(rows) - len(kept),
            "all_count": table.all_count,
        },
    )
    return HoldingListingDto(
        rows=kept,
        source="table-api",
        closed_omitted=len(rows) - len(kept),
        rows_dropped=rows_dropped,
        open_count=table.open_count,
        all_count=table.all_count,
        closed_count=table.closed_count,
    )
