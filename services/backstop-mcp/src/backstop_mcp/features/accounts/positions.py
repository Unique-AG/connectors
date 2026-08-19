"""Fan out `values` / `totalInvested` / `totalRedemptions` per listed account.

The existing per-user concurrency gate queues the burst — this module does not add another
limiter. Queueing is not bounding, though: the gate makes a 900-request fan-out orderly, not
short. `MAX_POSITION_ACCOUNTS` caps how many accounts are fanned out in one call, and the
count dropped is published rather than silently truncated.

One series failing is recorded on that row; siblings and other accounts continue.
`BackstopAuthError` aborts the whole fan-out: the credential is dead, and more calls will not
help.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Literal

from backstop_mcp.backstop_client import BackstopAuthError, BackstopClient
from backstop_mcp.features.accounts.latest import fetch_latest_figure
from backstop_mcp.features.accounts.types import (
    AccountListing,
    AccountPosition,
    AccountRecord,
    AumReconciliation,
    ProductPositions,
    ResolvedProduct,
    SeriesError,
    SeriesFigure,
    SeriesName,
)

logger = logging.getLogger(__name__)

# Three series per account, one request each, behind a per-user gate of 5. 500 accounts is
# already ~1500 queued requests; past that a single tool call stops being a call and starts
# being a batch job.
MAX_POSITION_ACCOUNTS = 500

# Assets under management and the balance sum are as-of different dates, exclude different
# accounts, and are summed across currencies without conversion. A cent-exact comparison would
# flag every real product, so the verdict is a tolerance: 0.5% of AUM, floored for tiny totals.
_AUM_RELATIVE_TOLERANCE = 0.005
_AUM_ABSOLUTE_TOLERANCE = 0.01

_SERIES: tuple[SeriesName, ...] = ("values", "totalInvested", "totalRedemptions")
_FIELD: dict[SeriesName, Literal["balance", "invested", "redemptions"]] = {
    "values": "balance",
    "totalInvested": "invested",
    "totalRedemptions": "redemptions",
}


async def fetch_positions(
    client: BackstopClient,
    accounts: Sequence[AccountRecord],
) -> tuple[AccountPosition, ...]:
    """Attach the three series to every account. Order matches `accounts`."""
    if not accounts:
        return ()
    return tuple(await asyncio.gather(*(_position(client, account) for account in accounts)))


async def _position(client: BackstopClient, account: AccountRecord) -> AccountPosition:
    results = await asyncio.gather(
        *(_series_point(client, account.id, series) for series in _SERIES),
        return_exceptions=True,
    )
    figures: dict[str, SeriesFigure | None] = {
        "balance": None,
        "invested": None,
        "redemptions": None,
    }
    errors: list[SeriesError] = []
    for series, result in zip(_SERIES, results, strict=True):
        if isinstance(result, BackstopAuthError):
            raise result
        if isinstance(result, BaseException):
            logger.warning(
                "accounts.series.failed",
                extra={"account_id": account.id, "series": series, "error": str(result)},
            )
            errors.append(SeriesError(series=series, message=str(result)))
            continue
        figures[_FIELD[series]] = result
    return AccountPosition(
        account=account,
        balance=figures["balance"],
        invested=figures["invested"],
        redemptions=figures["redemptions"],
        errors=tuple(errors),
    )


async def fetch_product_positions(
    client: BackstopClient,
    listing: AccountListing,
    *,
    product: ResolvedProduct,
) -> ProductPositions:
    """Fan out account series and product assets under management (AUM).

    AUM is the product's total reported value — the latest `/aums` point, same as each
    account series. Flag when it does not match the sum of returned account balances.
    """
    fanned = listing.accounts[:MAX_POSITION_ACCOUNTS]
    accounts_omitted = len(listing.accounts) - len(fanned)
    if accounts_omitted:
        logger.warning(
            "accounts.positions.fan_out_capped",
            extra={
                "product_id": product.id,
                "listed": len(listing.accounts),
                "cap": MAX_POSITION_ACCOUNTS,
            },
        )
    accounts, aum = await asyncio.gather(
        fetch_positions(client, fanned),
        fetch_product_aum(client, product.id),
    )
    return ProductPositions(
        product=product,
        accounts=accounts,
        closed_omitted=listing.closed_omitted,
        accounts_omitted=accounts_omitted,
        aum=aum,
        reconciliation=reconcile(accounts, aum),
    )


async def fetch_product_aum(client: BackstopClient, product_id: str) -> SeriesFigure | None:
    try:
        return await fetch_latest_figure(client, f"/products/{product_id}/aums")
    except BackstopAuthError:
        raise
    except Exception as exc:
        logger.warning("accounts.aum.failed", extra={"product_id": product_id, "error": str(exc)})
        return None


def reconcile(accounts: Sequence[AccountPosition], aum: SeriesFigure | None) -> AumReconciliation:
    """Sum the returned balances and compare them to latest assets under management.

    Missing balances (empty series, a point published without a number yet, or a failed fetch)
    are left out of the sum, not treated as zero. No balances at all, or no AUM figure, means
    there is nothing to compare — `diverges` stays false rather than guessing.

    `difference` is balances minus AUM, published so the caller can weigh a rounding gap against
    a missing account instead of reading a bare boolean.
    """
    balances = tuple(
        position.balance.valued.value
        for position in accounts
        if position.balance is not None
        and position.balance.valued is not None
        and position.balance.valued.value is not None
    )
    if not balances:
        return AumReconciliation()
    total = sum(balances)
    if aum is None or aum.valued is None or aum.valued.value is None:
        return AumReconciliation(balance_total=total)
    difference = total - aum.valued.value
    tolerance = max(abs(aum.valued.value) * _AUM_RELATIVE_TOLERANCE, _AUM_ABSOLUTE_TOLERANCE)
    return AumReconciliation(
        balance_total=total,
        difference=difference,
        diverges=abs(difference) > tolerance,
    )


async def _series_point(
    client: BackstopClient,
    account_id: str,
    series: SeriesName,
) -> SeriesFigure | None:
    return await fetch_latest_figure(client, f"/accounts/{account_id}/{series}")
