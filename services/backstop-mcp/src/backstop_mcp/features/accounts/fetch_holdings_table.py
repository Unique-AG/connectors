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
- **It fails open, and this module cannot close it.** A nonexistent id and a wrong-typed id
  (a product id, say) both return `200` with `accounts: []` and no `errors` — recorded in
  `docs/json/037` and `038` — indistinguishable from a party that genuinely owns nothing. An
  empty table is therefore only as trustworthy as `entity_id`, and `entity_id` is a plain `str`
  that nothing here can validate: `resolve_party` returns an id without a request unless
  `confirm_name=True`, so even the intended caller does not prove the party exists. Whoever
  exposes this as a tool has to decide how to close that — verifying the party on the
  empty-table branch is the cheap option, since it costs one request only when the answer would
  otherwise be "owns nothing".

`balance` here carries no as-of date and no `valueStatus`, though it matched the newest
`/accounts/{id}/values` point exactly on a measured account — including when that point was an
`ESTIMATE`. A dated, labelled figure needs the series endpoint.
"""

import logging

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts.api_responses import (
    AccountTableDataAttributes,
    AccountTableDataDocument,
)
from backstop_mcp.features.accounts.internal_dto import HoldingListingDto, HoldingRowDto

logger = logging.getLogger(__name__)

_TABLE_DATA_PATH = "/bsg-account-table-data"
_ENTITY_ID = "entityId"


class HoldingsTableShapeError(Exception):
    """Backstop's own counts contradict the rows it sent, so the payload is not readable.

    Raised rather than returned because the whole value of this endpoint is that one request is
    the answer; a table whose rows and counts disagree is not an answer, and the caller's
    documented fallback is. `openCount` / `allCount` / `closedCount` are computed upstream from
    the same table, so they are a free checksum on the field names this module reads: rename
    `accounts` and the counts still arrive, rename `closed` and `closedCount` still arrives.
    """


def _reject_contradictory_counts(table: AccountTableDataAttributes, *, entity_id: str) -> None:
    """Fail when the counts and the rows cannot both be true.

    Two shape changes this catches, both of which otherwise produce a confident wrong answer:
    a renamed `accounts` key (counts say 12, no rows arrive) and a renamed or absent `closed`
    (`closedCount` says 9, every row claims to be open). Counts are only compared when Backstop
    sent them; an endpoint that stops sending counts loses the checksum, not the answer.
    """
    rows = len(table.accounts)
    if table.all_count is not None and table.all_count != rows:
        raise HoldingsTableShapeError(
            f"table reported allCount={table.all_count} but sent {rows} rows for {entity_id}"
        )
    closed_rows = sum(1 for row in table.accounts if row.closed)
    if table.closed_count is not None and table.closed_count != closed_rows:
        raise HoldingsTableShapeError(
            f"table reported closedCount={table.closed_count}, "
            + f"but {closed_rows} of {rows} rows are marked closed for {entity_id}"
        )


async def fetch_holdings_table(
    client: BackstopClient,
    *,
    entity_id: str,
    include_closed: bool = False,
) -> HoldingListingDto:
    """A party's accounts with snapshot figures, in one request.

    `entity_id` should be a resolved party id — an unresolved one yields an empty table rather
    than an error (see the fail-open note above), which this function cannot detect. Raises
    whatever `BackstopClient` raises, plus `HoldingsTableShapeError`; the caller decides whether
    to fall back to the documented walk.
    """
    document = await client.get(
        _TABLE_DATA_PATH,
        schema=AccountTableDataDocument,
        params={_ENTITY_ID: entity_id},
    )
    table = document.table
    _reject_contradictory_counts(table, entity_id=entity_id)
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
