"""Subscriptions and redemptions for a mandatory transaction-date window.

Two collection walks: `/hedge-fund-account-subscriptions?include=fundAccount.owner` and
`/hedge-fund-account-redemptions?include=originalSubscription.fundAccount.owner`. A redemption
has no `fundAccount` of its own — it reaches an account only through
`originalSubscription`. Missing that chain is reported as `unattributed`, not dropped.
`filter[transactionDate]` is mandatory; an unfiltered read is 400. Actuals only
(`status=COMPLETED`), and how many rows that excluded is reported rather than swallowed.

Neither collection takes a product or account filter, so a walk is the whole window. Each is
capped at `MAX_CAPITAL_FLOW_SCAN_RECORDS` — the measured size is ~1,244 subscriptions since
2020, so the cap is headroom on this instance and a wall on a tenant where it is not.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import date
from typing import Literal, NamedTuple

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopClient,
    Included,
    IncludedResource,
)
from backstop_mcp.features.accounts.api_responses import (
    AccountAttributes,
    CapitalFlowAttributes,
    OwnerAttributes,
)
from backstop_mcp.features.accounts.responses import (
    MAX_CAPITAL_FLOW_SCAN_RECORDS,
    CapitalFlowPartyResponse,
    CapitalFlowRowResponse,
    CapitalFlowsResolvedResponse,
)

logger = logging.getLogger(__name__)

type FlowKind = Literal["subscription", "redemption"]
type FlowResource = BackstopApiResource[CapitalFlowAttributes]
_AccountInclude = IncludedResource[AccountAttributes]
_OwnerInclude = IncludedResource[OwnerAttributes]
_SubscriptionInclude = IncludedResource[CapitalFlowAttributes]


class _CapitalFlowScan(NamedTuple):
    """Actuals from one collection, plus how many pages it cost and what it skipped."""

    rows: tuple[CapitalFlowRowResponse, ...]
    non_actuals_dropped: int
    request_count: int
    scan_truncated: bool


class GetCapitalFlowsQuery:
    """Actual subscriptions and redemptions in a date window."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        start_date: date,
        end_date: date,
        max_rows: int,
        owner_id: str | None = None,
        account_ids: Sequence[str] | None = None,
    ) -> CapitalFlowsResolvedResponse:
        """Walk both collections for `start_date`..=`end_date` in two parallel calls."""
        subscriptions, redemptions = await asyncio.gather(
            self._scan_collection(
                "/hedge-fund-account-subscriptions",
                include="fundAccount.owner",
                start_date=start_date,
                end_date=end_date,
                kind="subscription",
            ),
            self._scan_collection(
                "/hedge-fund-account-redemptions",
                include="originalSubscription.fundAccount.owner",
                start_date=start_date,
                end_date=end_date,
                kind="redemption",
            ),
        )
        wanted_accounts = frozenset(account_ids) if account_ids is not None else None
        matched = tuple(
            row
            for row in self._newest_transaction_first((*subscriptions.rows, *redemptions.rows))
            if self._matches_owner_and_account_ids(
                row, owner_id=owner_id, account_ids=wanted_accounts
            )
        )
        return CapitalFlowsResolvedResponse(
            request_count=subscriptions.request_count + redemptions.request_count,
            flows=matched[:max_rows],
            total=len(matched),
            subscription_count=sum(1 for row in matched if row.kind == "subscription"),
            redemption_count=sum(1 for row in matched if row.kind == "redemption"),
            unattributed_count=sum(1 for row in matched if row.unattributed),
            non_actual_count=subscriptions.non_actuals_dropped + redemptions.non_actuals_dropped,
            truncated=len(matched) > max_rows,
            scan_truncated=subscriptions.scan_truncated or redemptions.scan_truncated,
        )

    async def _scan_collection(
        self,
        path: str,
        *,
        include: str,
        start_date: date,
        end_date: date,
        kind: FlowKind,
    ) -> _CapitalFlowScan:
        """One collection walk: the actuals, and the cost and coverage of getting them.

        `non_actuals_dropped` is returned rather than logged: a window holding 50 pending
        subscriptions must not report the same coverage as one holding none.
        """
        page = await self._client.paginate(
            path,
            schema=BackstopApiResource[CapitalFlowAttributes],
            params={
                "filter[transactionDate][ge]": start_date.isoformat(),
                "filter[transactionDate][le]": end_date.isoformat(),
                "include": include,
            },
            max_records=MAX_CAPITAL_FLOW_SCAN_RECORDS,
            page_size=200,
            parallel=True,
        )
        # One index per walk, not one per row: this array holds every side-loaded account, owner
        # and original subscription from every page, and each row follows two relationships into it.
        included = Included(page.included)
        rows = tuple(
            self._project_row(resource, kind=kind, included=included)
            for resource in page.items
            if self._has_completed_status(resource)
        )
        if page.truncated:
            logger.warning(
                "accounts.capital_flows.scan_ceiling_reached",
                extra={
                    "path": path,
                    "ceiling": MAX_CAPITAL_FLOW_SCAN_RECORDS,
                    "total_count": page.total_count,
                },
            )
        return _CapitalFlowScan(
            rows=rows,
            non_actuals_dropped=len(page.items) - len(rows),
            request_count=page.request_count,
            scan_truncated=page.truncated,
        )

    def _has_completed_status(self, resource: FlowResource) -> bool:
        return (resource.attributes.status or "").upper() == "COMPLETED"

    def _project_row(
        self,
        resource: FlowResource,
        *,
        kind: FlowKind,
        included: Included,
    ) -> CapitalFlowRowResponse:
        attributes = resource.attributes
        if kind == "subscription":
            account, owner = self._subscription_attribution(resource, included)
        else:
            account, owner = self._redemption_attribution(resource, included)
        return CapitalFlowRowResponse(
            id=resource.id,
            kind=kind,
            amount=attributes.amount,
            transaction_date=attributes.transaction_date,
            notice_date=attributes.notice_date,
            status=attributes.status,
            description=attributes.description,
            share_class=attributes.share_class,
            share_series=attributes.share_series,
            liquidating=attributes.liquidating,
            account=account,
            owner=owner,
            unattributed=account is None,
        )

    def _subscription_attribution(
        self, resource: FlowResource, included: Included
    ) -> tuple[CapitalFlowPartyResponse | None, CapitalFlowPartyResponse | None]:
        account = included.first(resource, "fundAccount", schema=_AccountInclude)
        owner = included.first(account, "owner", schema=_OwnerInclude)
        return (
            CapitalFlowPartyResponse.from_account(account),
            CapitalFlowPartyResponse.from_owner(owner),
        )

    def _redemption_attribution(
        self, resource: FlowResource, included: Included
    ) -> tuple[CapitalFlowPartyResponse | None, CapitalFlowPartyResponse | None]:
        original = included.first(resource, "originalSubscription", schema=_SubscriptionInclude)
        if original is None:
            return None, None
        return self._subscription_attribution(original, included)

    def _newest_transaction_first(
        self, rows: Sequence[CapitalFlowRowResponse]
    ) -> tuple[CapitalFlowRowResponse, ...]:
        """Newest `transaction_date` first, undated rows last.

        Sorting on `(date is None, date)` descending puts the undated group *first* — `True` sorts
        above `False` and `reverse=True` inverts the guard along with the date — so undated rows
        crowd real ones out at the row cap. Sorting undated rows as `date.min` descending lands
        them where they belong: after every dated row.
        """
        return tuple(
            sorted(
                rows,
                key=lambda row: date.min if row.transaction_date is None else row.transaction_date,
                reverse=True,
            )
        )

    def _matches_owner_and_account_ids(
        self,
        row: CapitalFlowRowResponse,
        *,
        owner_id: str | None,
        account_ids: frozenset[str] | None,
    ) -> bool:
        if owner_id is not None and (row.owner is None or row.owner.id != owner_id):
            return False
        return account_ids is None or (row.account is not None and row.account.id in account_ids)
