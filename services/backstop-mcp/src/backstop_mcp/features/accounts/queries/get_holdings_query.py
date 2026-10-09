"""A party's holdings: the undocumented UI table first, the documented walk when it fails.

`GET /bsg-account-table-data?entityId={partyId}` is one request with figures, but unsupported.
Any HTTP error (including a 401 that re-verified), timeout, unparseable body, or count/row
contradiction falls back to the documented walk: every `/accounts` page (`filter[owner]` is 400)
filtered to the owner, plus two series requests per owned account. Not a fallback trigger: an
empty table (a successful "owns nothing" — though table-data fails open on a bad id), a dead
credential (`BackstopAuthError`), or a rate limit.

The fallback cannot produce commitment, share of master, account term, or `otherId`; those are
omitted, never zeroed, and named in `omitted_fields`. Its `funded_date` is `accountStartDate`.

Tenure is measured on both paths over every owned account before the open/closed split, so
`include_closed=false` hides closed rows without shortening the relationship.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import date

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
    AccountSpanDto,
    HoldingFigureErrorDto,
    HoldingListingDto,
    HoldingRowDto,
    MoneyDto,
    SeriesFigureDto,
    ShareDto,
)
from backstop_mcp.features.accounts.utils import fetch_series, tenure_runs

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

    def __init__(self, *, client: BackstopClient, clock: Callable[[], date] = date.today) -> None:
        self._client: BackstopClient = client
        self._clock: Callable[[], date] = clock

    async def run(self, *, owner_id: str, include_closed: bool = False) -> HoldingListingDto:
        """`owner_id` should be a resolved party id; an unresolved one returns "owns nothing"."""
        try:
            return await self._holdings_table(owner_id=owner_id, include_closed=include_closed)
        except BackstopAuthError, BackstopRateLimitError:
            # Neither is "this endpoint is unavailable". A dead credential fails the walk the same
            # way, slower. A rate limit is worse: the fallback is a full /accounts walk plus two
            # requests per account, so falling back would answer a "slow down" with far more
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
            tenure=tenure_runs(
                (
                    AccountSpanDto(
                        start=row.funded_date, end=row.closed_date, is_open=not row.closed
                    )
                    for row in all_rows
                ),
                today=self._clock(),
            ),
        )

    async def _documented_holdings(
        self, *, owner_id: str, include_closed: bool
    ) -> HoldingListingDto:
        owned = await self._owned_accounts_for_party(owner_id=owner_id)
        listing = self._split_open(owned, include_closed=include_closed)
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
            tenure=tenure_runs(
                (
                    AccountSpanDto(
                        start=record.account_start_date,
                        end=record.closed_date,
                        is_open=record.is_open,
                    )
                    for record in owned
                ),
                today=self._clock(),
            ),
        )

    async def _owned_accounts_for_party(self, *, owner_id: str) -> tuple[AccountRecordDto, ...]:
        page = await self._client.paginate(
            "/accounts",
            schema=AccountApiResource,
            params={"include": "owner,investorType,product", "fields": ACCOUNT_LISTING_FIELDS},
            max_records=None,
            page_size=100,
            parallel=True,
        )
        return self._owned_accounts(page.items, included=page.included, owner_id=owner_id)

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
                extra={"account_id": account_id, "figure": field},
                exc_info=settled,
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
