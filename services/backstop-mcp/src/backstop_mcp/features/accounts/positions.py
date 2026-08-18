"""Fan out `values` / `totalInvested` / `totalRedemptions` per listed account.

The existing per-user concurrency gate queues the burst — this module does not add another
limiter. One series failing is recorded on that row; siblings and other accounts continue.
`BackstopAuthError` aborts the whole fan-out: the credential is dead, and more calls will not
help.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import date
from typing import Literal

from backstop_mcp.backstop_client import BackstopAuthError, BackstopClient
from backstop_mcp.features.accounts.latest import fetch_latest_point
from backstop_mcp.features.accounts.types import (
    AccountListing,
    AccountPosition,
    AccountRecord,
    ProductPositions,
    ResolvedProduct,
    SeriesError,
    SeriesName,
    SeriesPoint,
)

logger = logging.getLogger(__name__)

_SERIES: tuple[SeriesName, ...] = ("values", "totalInvested", "totalRedemptions")
_FIELD: dict[SeriesName, Literal["balance", "invested", "redemptions"]] = {
    "values": "balance",
    "totalInvested": "invested",
    "totalRedemptions": "redemptions",
}


async def fetch_positions(
    client: BackstopClient,
    accounts: Sequence[AccountRecord],
    *,
    today: date,
) -> tuple[AccountPosition, ...]:
    """Attach the three series to every account. Order matches `accounts`."""
    if not accounts:
        return ()
    return tuple(
        await asyncio.gather(*(_position(client, account, today=today) for account in accounts))
    )


async def _position(
    client: BackstopClient,
    account: AccountRecord,
    *,
    today: date,
) -> AccountPosition:
    results = await asyncio.gather(
        *(_series_point(client, account.id, series, today=today) for series in _SERIES),
        return_exceptions=True,
    )
    figures: dict[str, SeriesPoint | None] = {
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
    today: date,
) -> ProductPositions:
    """Fan out account series and product assets under management (AUM).

    AUM is the product's total reported value. Flag when it does not match the sum of
    returned account balances.
    """
    accounts, aum = await asyncio.gather(
        fetch_positions(client, listing.accounts, today=today),
        fetch_product_aum(client, product.id, today=today),
    )
    return ProductPositions(
        product=product,
        accounts=accounts,
        closed_omitted=listing.closed_omitted,
        aum=aum,
        aum_diverges=aum_diverges(accounts, aum),
    )


async def fetch_product_aum(
    client: BackstopClient,
    product_id: str,
    *,
    today: date,
) -> SeriesPoint | None:
    try:
        return await fetch_latest_point(client, f"/products/{product_id}/aums", today=today)
    except BackstopAuthError:
        raise
    except Exception as exc:
        logger.warning("accounts.aum.failed", extra={"product_id": product_id, "error": str(exc)})
        return None


def aum_diverges(accounts: Sequence[AccountPosition], aum: SeriesPoint | None) -> bool:
    """True when latest assets under management (the product's total value) ≠ balance sum.

    Missing balances (empty series or a failed fetch) are left out of the sum, not treated as
    zero — that is the usual cause of a flag when closed-but-still-valued accounts were omitted.
    No AUM figure, or one without a value, cannot be compared.
    """
    if aum is None or aum.value is None:
        return False
    total = sum(
        position.balance.value
        for position in accounts
        if position.balance is not None and position.balance.value is not None
    )
    return round(total, 2) != round(aum.value, 2)


async def _series_point(
    client: BackstopClient,
    account_id: str,
    series: SeriesName,
    *,
    today: date,
) -> SeriesPoint | None:
    return await fetch_latest_point(client, f"/accounts/{account_id}/{series}", today=today)
