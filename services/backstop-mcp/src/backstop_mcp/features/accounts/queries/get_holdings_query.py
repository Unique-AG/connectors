"""A party's holdings: the undocumented UI table first, the documented walk when it fails.

`_holdings_table` is one request and carries figures. It is also an unsupported endpoint that
can disappear on another tenant, so this query owns the decision of when to stop trusting it
and what the documented path can honestly produce instead.

**What triggers the fallback.** Any HTTP error, timeout, or unparseable body from table-data,
including a mid-session 401 that re-verified (`BackstopTransientAuthError`): the credential still
works, this unsupported endpoint did not — same as a 404. Deliberately *not*:

- **An empty table.** `accounts: []` is a successful "owns nothing" and walking 815 accounts to
  confirm it would be pure cost. The catch is that table-data **fails open** — a nonexistent id
  and a wrong-typed id return the same empty `200`. `owner_id` should therefore be a resolved
  party id, but nothing here can verify that; see the fail-open note on `_holdings_table`.
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

The table endpoint itself is undocumented. It was found by watching the Backstop web app: one
`GET /bsg-account-table-data?entityId={partyId}` serves the account table a user looks at.
Paging params are ignored; row order is not stable; a product id fails open as an empty table.
Keep the documented fallback working. The counts checked in `_reject_contradictory_counts` are
the tripwire for a silent shape change.

By-party listing on the fallback walks `/accounts` because `filter[owner]` is 400 and neither
party collection exposes an `accounts` subcollection. Open means the `closedDate` key is absent.
"""

import asyncio
import logging
from collections.abc import Sequence

from backstop_mcp.backstop_client import (
    BackstopAuthError,
    BackstopClient,
    BackstopRateLimitError,
    BackstopTransientAuthError,
    Included,
    IncludedResource,
)
from backstop_mcp.features.accounts.api_responses import (
    ACCOUNT_LISTING_FIELDS,
    AccountApiResource,
    AccountTableDataAttributes,
    AccountTableDataDocument,
    OwnerAttributes,
)
from backstop_mcp.features.accounts.internal_dto import (
    AccountListingDto,
    AccountOwnerDto,
    AccountRecordDto,
    HoldingFigureErrorDto,
    HoldingListingDto,
    HoldingRowDto,
    MoneyDto,
    SeriesFigureDto,
    ShareDto,
)
from backstop_mcp.features.accounts.utils import fetch_series

logger = logging.getLogger(__name__)

_OWNER = "owner"

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


class HoldingsTableShapeError(Exception):
    """Backstop's own counts contradict the rows it sent, so the payload is not readable.

    Raised rather than returned because the whole value of the table endpoint is that one
    request is the answer; a table whose rows and counts disagree is not an answer, and the
    documented fallback is. `openCount` / `allCount` / `closedCount` are computed upstream from
    the same table, so they are a free checksum on the field names this query reads.
    """


class GetHoldingsQuery:
    """A party's holdings with figures, from whichever path is available."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, owner_id: str, include_closed: bool = False) -> HoldingListingDto:
        """`owner_id` should be a resolved party id; an unresolved one returns "owns nothing"."""
        try:
            return await self._holdings_table(owner_id=owner_id, include_closed=include_closed)
        except BackstopAuthError, BackstopRateLimitError:
            # Neither is "this endpoint is unavailable". A dead credential fails the walk the same
            # way, slower. A rate limit is worse: the fallback is ~9 pages plus two requests per
            # account, so falling back would answer a "slow down" with an order of magnitude more
            # load — and a rate limit is the likeliest transient failure of an unbounded payload.
            raise
        except Exception as exc:
            # Broad on purpose: HTTP status, transport timeout, schema-validation failure, a
            # counts-versus-rows contradiction, and a 401 that re-verified
            # (`BackstopTransientAuthError`) all mean the same thing here — the unsupported
            # endpoint did not answer usably, so use the documented one.
            logger.warning(
                "accounts.holdings.table_unavailable_using_documented_walk",
                extra={"owner_id": owner_id},
                exc_info=exc,
            )
        return await self._documented_holdings(owner_id=owner_id, include_closed=include_closed)

    async def _holdings_table(self, *, owner_id: str, include_closed: bool) -> HoldingListingDto:
        document = await self._client.get(
            "/bsg-account-table-data",
            schema=AccountTableDataDocument,
            params={"entityId": owner_id},
        )
        table = document.table
        self._reject_contradictory_counts(table, entity_id=owner_id)
        all_rows = tuple(
            HoldingRowDto.from_attributes(row) for row in table.accounts if row.account is not None
        )
        rows_dropped = len(table.accounts) - len(all_rows)
        if rows_dropped:
            logger.warning(
                "accounts.holdings_table.rows_without_account_id",
                extra={
                    "entity_id": owner_id,
                    "dropped": rows_dropped,
                    "returned": len(table.accounts),
                },
            )
        rows = all_rows if include_closed else tuple(row for row in all_rows if not row.closed)
        logger.info(
            "accounts.holdings_table.fetched",
            extra={
                "entity_id": owner_id,
                "rows": len(rows),
                "closed_omitted": len(all_rows) - len(rows),
                "all_count": table.all_count,
            },
        )
        return HoldingListingDto(
            rows=rows,
            source="table-api",
            closed_omitted=len(all_rows) - len(rows),
            rows_dropped=rows_dropped,
            open_count=table.open_count,
            all_count=table.all_count,
            closed_count=table.closed_count,
        )

    async def _documented_holdings(
        self, *, owner_id: str, include_closed: bool
    ) -> HoldingListingDto:
        listing = await self._accounts_for_party(owner_id=owner_id, include_closed=include_closed)
        # `return_exceptions` so one row raising does not leave its siblings unawaited; the first
        # failure is then re-raised deliberately.
        settled = await asyncio.gather(
            *(self._row_with_figures(account) for account in listing.accounts),
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
            closed_count=self._closed_count(
                listing.accounts, closed_omitted=listing.closed_omitted
            ),
            source="accounts-api",
            omitted_fields=FALLBACK_OMITTED_FIELDS,
        )

    async def _accounts_for_party(
        self, *, owner_id: str, include_closed: bool
    ) -> AccountListingDto:
        page = await self._client.paginate(
            "/accounts",
            schema=AccountApiResource,
            params={"include": "owner,investorType,product", "fields": ACCOUNT_LISTING_FIELDS},
            max_records=None,
            page_size=100,
            parallel=True,
        )
        return self._split_open(
            self._owned_accounts(page.items, included=page.included, owner_id=owner_id),
            include_closed=include_closed,
        )

    def _split_open(
        self, records: Sequence[AccountRecordDto], *, include_closed: bool
    ) -> AccountListingDto:
        if include_closed:
            return AccountListingDto(accounts=tuple(records), closed_omitted=0)
        open_accounts = tuple(record for record in records if record.is_open)
        return AccountListingDto(
            accounts=open_accounts,
            closed_omitted=len(records) - len(open_accounts),
        )

    async def _row_with_figures(self, account: AccountRecordDto) -> HoldingRowDto:
        settled = await asyncio.gather(
            fetch_series(self._client, f"/accounts/{account.id}/values"),
            fetch_series(self._client, f"/accounts/{account.id}/percentageOfFundHistory"),
            return_exceptions=True,
        )
        balance_series, balance_error = self._series_or_figure_error(
            settled[0], account_id=account.id, field="balance"
        )
        share_series, share_error = self._series_or_figure_error(
            settled[1], account_id=account.id, field="percentage_of_product"
        )
        return HoldingRowDto(
            account_id=account.id,
            product_id=account.product.id if account.product else None,
            product_short_name=account.product.short_name if account.product else None,
            investor_id=account.owner.id if account.owner else None,
            investor_resource_type=account.owner.resource_type if account.owner else None,
            funded_date=account.account_start_date,
            closed_date=account.closed_date,
            closed=not account.is_open,
            balance=self._money(balance_series, currency=account.currency),
            balance_as_of=(
                balance_series.valued.date if balance_series and balance_series.valued else None
            ),
            balance_status=(
                balance_series.valued.value_status
                if balance_series and balance_series.valued
                else None
            ),
            percentage_of_product=self._share(share_series),
            figure_errors=tuple(
                error for error in (balance_error, share_error) if error is not None
            ),
        )

    def _series_or_figure_error(
        self,
        settled: SeriesFigureDto | BaseException | None,
        *,
        account_id: str,
        field: str,
    ) -> tuple[SeriesFigureDto | None, HoldingFigureErrorDto | None]:
        """The series payload, or `None` when that series failed. Auth still aborts the row."""
        if isinstance(settled, BackstopAuthError | BackstopTransientAuthError):
            raise settled
        if isinstance(settled, BaseException):
            # One series failing costs that field, not the row: an account with a balance and
            # no share-of-fund is still the answer to "what do they hold". The reason is
            # carried so the omission does not read as "Backstop publishes no number".
            message = f"{type(settled).__name__}: {settled}"
            logger.warning(
                "accounts.holdings.fallback_series_failed",
                extra={"account_id": account_id, "figure": field, "error": message},
            )
            return None, HoldingFigureErrorDto(figure=field, message=message)
        return settled, None

    def _reject_contradictory_counts(
        self, table: AccountTableDataAttributes, *, entity_id: str
    ) -> None:
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

    def _owned_accounts(
        self,
        resources: Sequence[AccountApiResource],
        *,
        included: Sequence[dict[str, object]],
        owner_id: str,
    ) -> tuple[AccountRecordDto, ...]:
        side_loads = Included(included)
        return tuple(
            AccountRecordDto.from_resource(resource, included=side_loads)
            for resource in resources
            if self._owns(resource, included=side_loads, owner_id=owner_id)
        )

    def _owns(
        self,
        resource: AccountApiResource,
        *,
        included: Included,
        owner_id: str,
    ) -> bool:
        # Linkage id first — it costs nothing and works without the `owner` include.
        if owner_id in resource.related_ids(_OWNER):
            return True
        owner = AccountOwnerDto.from_included(
            included.first(resource, _OWNER, schema=IncludedResource[OwnerAttributes])
        )
        return owner is not None and owner.id == owner_id

    def _closed_count(self, accounts: Sequence[AccountRecordDto], *, closed_omitted: int) -> int:
        """Closed accounts the party has, whether or not they were kept.

        With `include_closed` off they were filtered out and only `closed_omitted` knows about
        them; with it on they are in `accounts` and `closed_omitted` is zero. Summing both is
        correct in each case and does not double-count.
        """
        return closed_omitted + sum(1 for account in accounts if not account.is_open)

    def _money(self, series: SeriesFigureDto | None, *, currency: str | None) -> MoneyDto | None:
        """A published number, or `None`. A real `0.0` is kept; "no number yet" is not zeroed."""
        if series is None or series.valued is None or series.valued.value is None:
            return None
        return MoneyDto(amount=series.valued.value, currency=currency)

    def _share(self, series: SeriesFigureDto | None) -> ShareDto | None:
        """`percentageOfFundHistory` is a fraction (`0.796` = 79.6%)."""
        if series is None or series.valued is None or series.valued.value is None:
            return None
        return ShareDto(fraction=series.valued.value)
