"""A party's holdings: the undocumented UI table first, the documented walk when it fails.

`fetch_holdings_table` is one request and carries figures. It is also an unsupported endpoint that
can disappear on another tenant, so this module owns the decision of when to stop trusting it and
what the documented path can honestly produce instead.

**What triggers the fallback.** Any HTTP error, timeout, or unparseable body from table-data.
Deliberately *not*:

- **An empty table.** `accounts: []` is a successful "owns nothing" and walking 815 accounts to
  confirm it would be pure cost. The catch is that table-data **fails open** — a nonexistent id
  and a wrong-typed id return the same empty `200`. `owner_id` should therefore be a resolved
  party id, but nothing here can verify that; see the fail-open note in `fetch_holdings_table`.
- **`BackstopAuthError`.** The credential is dead; the documented walk would fail the same way,
  slower.

**What the fallback cannot produce.** The documented `/accounts` walk has no commitment, no
share-of-master, no account-term reference, and no `otherId` in the listing fieldset; the series
endpoints give a number with no currency rendering. Those fields are **omitted, never zeroed**,
and are named in `omitted_fields` so the answer cannot be read as "this party has no commitment".
`funded_date` falls back to `accountStartDate`, which is a near neighbour of table-data's
`fundedDate` rather than the same field.

**Cost.** Table-data is 1 request. The fallback is ~9 parallel pages (measured: 9.1s/4.3 MiB for
this instance's 815 accounts) plus 2 series requests per *owned* account — which is affordable
only because a party owns a handful of them. It is never run product-wide.
"""

import asyncio
import logging
from collections.abc import Sequence

from backstop_mcp.backstop_client import (
    BackstopAuthError,
    BackstopClient,
    BackstopRateLimitError,
)
from backstop_mcp.features.accounts.fetch_accounts_for_party import fetch_accounts_for_party
from backstop_mcp.features.accounts.fetch_holdings_table import fetch_holdings_table
from backstop_mcp.features.accounts.fetch_series import fetch_series
from backstop_mcp.features.accounts.internal_dto import (
    AccountRecordDto,
    HoldingFigureErrorDto,
    HoldingListingDto,
    HoldingRowDto,
    MoneyDto,
    SeriesFigureDto,
    ShareDto,
)

logger = logging.getLogger(__name__)

_BALANCE_SERIES = "values"
_SHARE_SERIES = "percentageOfFundHistory"

# The row field each fallback series fills, used for both the request and the error label so a
# failure names what the caller is missing rather than the upstream series.
_FALLBACK_FIGURES: tuple[str, ...] = ("balance", "percentage_of_product")

# Carried on every fallback answer so a missing figure reads as "not available on this path"
# rather than as "zero". These are field names, not prose: the response layer turns them into the
# caveat the model is shown, which keeps the wording out of the domain layer.
#
# `funded_date` is deliberately absent from this list. It is populated on the fallback path, but
# from `accountStartDate` rather than the table endpoint's `fundedDate` — a change of meaning, not
# an omission, and the response layer says so separately.
FALLBACK_OMITTED_FIELDS: tuple[str, ...] = (
    "commitment",
    "unfunded_commitment",
    "percentage_of_master",
    "account_term_id",
    "other_id",
)


async def fetch_holdings(
    client: BackstopClient,
    *,
    owner_id: str,
    include_closed: bool = False,
) -> HoldingListingDto:
    """A party's holdings with figures, from whichever path is available.

    `owner_id` should be a resolved party id; an unresolved one returns "owns nothing" rather
    than an error, and neither path can tell the difference. See the module docstring.
    """
    try:
        return await fetch_holdings_table(client, entity_id=owner_id, include_closed=include_closed)
    except (BackstopAuthError, BackstopRateLimitError):
        # Neither is "this endpoint is unavailable". A dead credential fails the walk the same
        # way, slower. A rate limit is worse: the fallback is ~9 pages plus two requests per
        # account, so falling back would answer a "slow down" with an order of magnitude more
        # load — and a rate limit is the likeliest transient failure of an unbounded payload.
        raise
    except Exception as exc:
        # Broad on purpose: HTTP status, transport timeout, schema-validation failure and a
        # counts-versus-rows contradiction all mean the same thing here — the unsupported
        # endpoint did not answer usably, so use the documented one.
        logger.warning(
            "accounts.holdings.table_unavailable_using_documented_walk",
            extra={"owner_id": owner_id, "error": f"{type(exc).__name__}: {exc}"},
        )
    return await _fetch_documented_holdings(
        client, owner_id=owner_id, include_closed=include_closed
    )


async def _fetch_documented_holdings(
    client: BackstopClient,
    *,
    owner_id: str,
    include_closed: bool,
) -> HoldingListingDto:
    listing = await fetch_accounts_for_party(
        client, owner_id=owner_id, include_closed=include_closed
    )
    # `return_exceptions` so one row raising does not leave its siblings unawaited; the first
    # failure is then re-raised deliberately.
    settled = await asyncio.gather(
        *(_row_with_figures(client, account) for account in listing.accounts),
        return_exceptions=True,
    )
    rows: list[HoldingRowDto] = []
    for result in settled:
        if isinstance(result, BaseException):
            raise result
        rows.append(result)
    return HoldingListingDto(
        rows=tuple(rows),
        closed_omitted=listing.closed_omitted,
        open_count=sum(1 for account in listing.accounts if account.is_open),
        all_count=len(listing.accounts) + listing.closed_omitted,
        closed_count=_closed_count(listing.accounts, closed_omitted=listing.closed_omitted),
        source="accounts-api",
        omitted_fields=FALLBACK_OMITTED_FIELDS,
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
    figures: list[SeriesFigureDto | None] = []
    errors: list[HoldingFigureErrorDto] = []
    for figure_name, result in zip(_FALLBACK_FIGURES, results, strict=True):
        if isinstance(result, BackstopAuthError):
            raise result
        if isinstance(result, BaseException):
            # One series failing costs that figure, not the row: an account with a balance and no
            # share-of-fund is still the answer to "what do they hold". The reason is carried so
            # the omission does not read as "Backstop publishes no number".
            message = f"{type(result).__name__}: {result}"
            logger.warning(
                "accounts.holdings.fallback_series_failed",
                extra={"account_id": account.id, "figure": figure_name, "error": message},
            )
            errors.append(HoldingFigureErrorDto(figure=figure_name, message=message))
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
        balance=_money(balance, currency=account.currency),
        balance_as_of=balance.valued.date if balance and balance.valued else None,
        balance_status=balance.valued.value_status if balance and balance.valued else None,
        percentage_of_product=_share(share),
        figure_errors=tuple(errors),
    )


def _money(figure: SeriesFigureDto | None, *, currency: str | None) -> MoneyDto | None:
    """A published number, or `None`. A real `0.0` is kept; "no number yet" is not zeroed."""
    if figure is None or figure.valued is None or figure.valued.value is None:
        return None
    return MoneyDto(amount=figure.valued.value, currency=currency)


def _share(figure: SeriesFigureDto | None) -> ShareDto | None:
    """`percentageOfFundHistory` is a fraction (`0.796` = 79.6%), verified against a live series."""
    if figure is None or figure.valued is None or figure.valued.value is None:
        return None
    return ShareDto(fraction=figure.valued.value)


async def _series_figure(
    client: BackstopClient, account_id: str, series: str
) -> SeriesFigureDto | None:
    """The whole figure, not just its number, so the as-of date and status survive.

    `fetch_series` already separates the newest row from the newest row carrying a value; both
    matter here, because the valued one can be months older than the newest one.
    """
    return await fetch_series(client, f"/accounts/{account_id}/{series}")
