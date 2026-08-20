"""A party's holdings: the undocumented UI table first, the documented walk when it fails.

`fetch_holdings_table` is one request and carries figures. It is also an unsupported endpoint that
can disappear on another tenant, so this module owns the decision of when to stop trusting it and
what the documented path can honestly produce instead.

**What triggers the fallback.** Any HTTP error, timeout, or unparseable body from table-data.
Deliberately *not*:

- **An empty table.** `accounts: []` is a successful "owns nothing" and walking 815 accounts to
  confirm it would be pure cost. The catch is that table-data **fails open** — a nonexistent id
  and a wrong-typed id return the same empty `200` — which is why `owner_id` must be a resolved
  party id and never a caller-supplied string.
- **`BackstopAuthError`.** The credential is dead; the documented walk would fail the same way,
  slower.

**What the fallback cannot produce.** The documented `/accounts` walk has no commitment, no
share-of-master, no account-term reference, and no `otherId` in the listing fieldset; the series
endpoints give a number with no currency rendering. Those fields are **omitted, never zeroed**,
and `fallback_note` names them so the answer cannot be read as "this party has no commitment".
`funded_date` falls back to `accountStartDate`, which is a near neighbour of table-data's
`fundedDate` rather than the same field — also named in the note.

**Cost.** Table-data is 1 request. The fallback is ~9 parallel pages (measured: 9.1s/4.3 MiB for
this instance's 815 accounts) plus 2 series requests per *owned* account — which is affordable
only because a party owns a handful of them. It is never run product-wide.
"""

import asyncio
import logging
from collections.abc import Sequence

from backstop_mcp.backstop_client import BackstopAuthError, BackstopClient
from backstop_mcp.features.accounts.fetch_accounts_for_party import fetch_accounts_for_party
from backstop_mcp.features.accounts.fetch_holdings_table import fetch_holdings_table
from backstop_mcp.features.accounts.fetch_series import fetch_series
from backstop_mcp.features.accounts.internal_dto import (
    AccountRecordDto,
    HoldingListingDto,
    HoldingRowDto,
    MoneyDto,
    ShareDto,
)

logger = logging.getLogger(__name__)

_BALANCE_SERIES = "values"
_SHARE_SERIES = "percentageOfFundHistory"

# Named on every fallback answer, so a missing figure reads as "not available on this path"
# rather than as "zero". `funded_date` is listed because it changes meaning, not because it is
# absent.
FALLBACK_OMITTED_FIELDS: tuple[str, ...] = (
    "commitment",
    "unfunded_commitment",
    "percentage_of_master",
    "account_term_id",
    "other_id",
)

_FALLBACK_NOTE = (
    "Backstop's account-table endpoint was unavailable, so this came from the documented "
    "/accounts walk plus per-account series. Not available on this path and omitted rather "
    f"than zeroed: {', '.join(FALLBACK_OMITTED_FIELDS)}. Do not answer questions about those "
    "fields from this payload. `funded_date` is the account's accountStartDate here, which is a "
    "near neighbour of the table endpoint's fundedDate rather than the same field. Money figures "
    "carry an amount but no formatted rendering."
)


async def fetch_holdings(
    client: BackstopClient,
    *,
    owner_id: str,
    include_closed: bool = False,
) -> HoldingListingDto:
    """A party's holdings with figures, from whichever path is available.

    `owner_id` must be a resolved party id — see the fail-open note in the module docstring.
    """
    try:
        return await fetch_holdings_table(client, entity_id=owner_id, include_closed=include_closed)
    except BackstopAuthError:
        raise
    except Exception as exc:
        # Broad on purpose: HTTP status, transport timeout and schema-validation failures all
        # mean the same thing here — the unsupported endpoint did not answer, so use the
        # documented one. Auth is re-raised above because retrying it cannot help.
        logger.warning(
            "accounts.holdings.table_unavailable_using_documented_walk",
            extra={"owner_id": owner_id, "error": f"{type(exc).__name__}: {exc}"},
        )
    return await _documented_holdings(client, owner_id=owner_id, include_closed=include_closed)


async def _documented_holdings(
    client: BackstopClient,
    *,
    owner_id: str,
    include_closed: bool,
) -> HoldingListingDto:
    listing = await fetch_accounts_for_party(
        client, owner_id=owner_id, include_closed=include_closed
    )
    rows = await asyncio.gather(
        *(_row_with_figures(client, account) for account in listing.accounts)
    )
    return HoldingListingDto(
        rows=tuple(rows),
        closed_omitted=listing.closed_omitted,
        open_count=sum(1 for account in listing.accounts if account.is_open),
        all_count=len(listing.accounts) + listing.closed_omitted,
        closed_count=_closed_count(listing.accounts, closed_omitted=listing.closed_omitted),
        fallback_note=_FALLBACK_NOTE,
    )


def _closed_count(accounts: Sequence[AccountRecordDto], *, closed_omitted: int) -> int:
    """Closed accounts the party has, whether or not they were kept.

    With `include_closed` off they were filtered out and only `closed_omitted` knows about them;
    with it on they are in `accounts` and `closed_omitted` is zero. Summing both is correct in
    each case and does not double-count.
    """
    return closed_omitted + sum(1 for account in accounts if not account.is_open)


async def _row_with_figures(client: BackstopClient, account: AccountRecordDto) -> HoldingRowDto:
    """One documented row. A failed series omits that figure; a failed auth aborts the fan-out."""
    results = await asyncio.gather(
        _series_figure(client, account.id, _BALANCE_SERIES),
        _series_figure(client, account.id, _SHARE_SERIES),
        return_exceptions=True,
    )
    figures: list[float | None] = []
    for series, result in zip((_BALANCE_SERIES, _SHARE_SERIES), results, strict=True):
        if isinstance(result, BackstopAuthError):
            raise result
        if isinstance(result, BaseException):
            # One series failing costs that figure, not the row: an account with a balance and no
            # share-of-fund is still the answer to "what do they hold".
            logger.warning(
                "accounts.holdings.fallback_series_failed",
                extra={
                    "account_id": account.id,
                    "series": series,
                    "error": f"{type(result).__name__}: {result}",
                },
            )
            figures.append(None)
            continue
        figures.append(result)
    balance, share = figures
    return HoldingRowDto(
        account_id=account.id,
        product_id=account.product.id if account.product else None,
        product_short_name=account.product.short_name if account.product else None,
        investor_id=account.owner.id if account.owner else None,
        investor_resource_type=account.owner.resource_type if account.owner else None,
        funded_date=account.account_start_date,
        closed_date=account.closed_date,
        closed=not account.is_open,
        balance=None if balance is None else MoneyDto(amount=balance, currency=account.currency),
        percentage_of_product=None if share is None else ShareDto(fraction=share),
    )


async def _series_figure(client: BackstopClient, account_id: str, series: str) -> float | None:
    """The latest *valued* point on one series, or `None` when nothing is published yet.

    A published `0.0` comes back as `0.0`, not `None` — a real zero balance is an answer, and
    collapsing it to "no figure" would read as "we could not find out".
    """
    figure = await fetch_series(client, f"/accounts/{account_id}/{series}")
    if figure is None or figure.valued is None:
        return None
    return figure.valued.value
