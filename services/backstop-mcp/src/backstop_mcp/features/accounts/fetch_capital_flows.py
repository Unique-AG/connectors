"""Subscriptions and redemptions for a mandatory transaction-date window.

Two collection walks: `/hedge-fund-account-subscriptions?include=fundAccount.owner` and
`/hedge-fund-account-redemptions?include=originalSubscription.fundAccount`. A redemption
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
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Literal, cast

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopClient,
    IncludedIndex,
    IncludedResource,
    follow_indexed,
    included_resource,
    index_included,
)
from backstop_mcp.features.accounts.api_responses import (
    AccountAttributes,
    CapitalFlowAttributes,
    OwnerAttributes,
)
from backstop_mcp.features.accounts.internal_dto import (
    CapitalFlowDto,
    CapitalFlowPartyDto,
    CapitalFlowsFetchDto,
    CapitalFlowWalkDto,
)

logger = logging.getLogger(__name__)

_SUBS_PATH = "/hedge-fund-account-subscriptions"
_REDS_PATH = "/hedge-fund-account-redemptions"
_PAGE_SIZE = 200
_ACTUAL = "COMPLETED"

# Scan ceiling per collection. 1,244 subscriptions since 2020 on this instance, so this is
# ~8x headroom; past it the walk stops and says so rather than accumulating every row of a
# collection this tool cannot filter server-side.
MAX_CAPITAL_FLOW_SCAN_RECORDS = 10_000

type FlowKind = Literal["subscription", "redemption"]
type FlowResource = BackstopApiResource[CapitalFlowAttributes]


def _indexed_by_ref(
    index: IncludedIndex, ref: Mapping[str, object] | None
) -> dict[str, object] | None:
    """The `included` entry a raw `{id, type}` linkage object points at.

    Backstop nests the chains this module follows one hop deeper than a relationship name
    reaches: `originalSubscription` arrives as an `included` entry, and its own `fundAccount`
    linkage is a plain dict in that entry rather than a field on a parsed resource. So the ref
    is resolved against the same index `follow_indexed` uses.
    """
    if ref is None:
        return None
    ref_id, ref_type = ref.get("id"), ref.get("type")
    if not isinstance(ref_id, str) or not isinstance(ref_type, str):
        return None
    return index.get((ref_type, ref_id))


def _relationship_data(raw: Mapping[str, object], name: str) -> dict[str, object] | None:
    relationships = raw.get("relationships")
    if not isinstance(relationships, dict):
        return None
    typed_relationships = cast(dict[str, object], relationships)
    relationship_value = typed_relationships.get(name)
    if not isinstance(relationship_value, dict):
        return None
    typed_relationship = cast(dict[str, object], relationship_value)
    data = typed_relationship.get("data")
    if not isinstance(data, dict):
        return None
    return cast(dict[str, object], data)


def _account_chip(raw: dict[str, object] | None) -> CapitalFlowPartyDto | None:
    account = included_resource(raw, schema=IncludedResource[AccountAttributes])
    if account is None:
        return None
    return CapitalFlowPartyDto(
        id=account.id, name=account.attributes.name, resource_type=account.type
    )


def _owner_chip(raw: dict[str, object] | None) -> CapitalFlowPartyDto | None:
    owner = included_resource(raw, schema=IncludedResource[OwnerAttributes])
    if owner is None:
        return None
    return CapitalFlowPartyDto(id=owner.id, name=owner.attributes.name, resource_type=owner.type)


def _subscription_attribution(
    resource: FlowResource, index: IncludedIndex
) -> tuple[CapitalFlowPartyDto | None, CapitalFlowPartyDto | None]:
    accounts = follow_indexed(index, resource, "fundAccount")
    account_raw = accounts[0] if accounts else None
    owner_raw = _indexed_by_ref(index, _relationship_data(account_raw or {}, "owner"))
    return _account_chip(account_raw), _owner_chip(owner_raw)


def _redemption_attribution(
    resource: FlowResource, index: IncludedIndex
) -> tuple[CapitalFlowPartyDto | None, CapitalFlowPartyDto | None]:
    originals = follow_indexed(index, resource, "originalSubscription")
    if not originals:
        return None, None
    account_raw = _indexed_by_ref(index, _relationship_data(originals[0], "fundAccount"))
    owner_raw = _indexed_by_ref(index, _relationship_data(account_raw or {}, "owner"))
    return _account_chip(account_raw), _owner_chip(owner_raw)


def _project_row(
    resource: FlowResource,
    *,
    kind: FlowKind,
    index: IncludedIndex,
) -> CapitalFlowDto | None:
    attributes = resource.attributes
    if (attributes.status or "").upper() != _ACTUAL:
        return None
    if kind == "subscription":
        account, owner = _subscription_attribution(resource, index)
    else:
        account, owner = _redemption_attribution(resource, index)
    return CapitalFlowDto(
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


def _date_params(*, start_date: date, end_date: date) -> dict[str, object]:
    return {
        "filter[transactionDate][ge]": start_date.isoformat(),
        "filter[transactionDate][le]": end_date.isoformat(),
    }


async def _walk(
    client: BackstopClient,
    path: str,
    *,
    include: str,
    start_date: date,
    end_date: date,
    kind: FlowKind,
) -> CapitalFlowWalkDto:
    """One collection walk: the actuals, and the cost and coverage of getting them.

    `non_actuals_dropped` is returned rather than logged: a window holding 50 pending
    subscriptions must not report the same coverage as one holding none.
    """
    page = await client.paginate(
        path,
        schema=BackstopApiResource[CapitalFlowAttributes],
        params={**_date_params(start_date=start_date, end_date=end_date), "include": include},
        max_records=MAX_CAPITAL_FLOW_SCAN_RECORDS,
        page_size=_PAGE_SIZE,
        parallel=True,
    )
    # One index per walk, not one per row: this array holds every side-loaded account, owner and
    # original subscription from every page, and each row follows two relationships into it.
    index = index_included(page.included)
    rows: list[CapitalFlowDto] = []
    for resource in page.items:
        projected = _project_row(resource, kind=kind, index=index)
        if projected is None:
            continue
        rows.append(projected)
    dropped = len(page.items) - len(rows)
    if page.truncated:
        logger.warning(
            "accounts.capital_flows.scan_ceiling_reached",
            extra={
                "path": path,
                "ceiling": MAX_CAPITAL_FLOW_SCAN_RECORDS,
                "total_count": page.total_count,
            },
        )
    return CapitalFlowWalkDto(
        rows=tuple(rows),
        non_actuals_dropped=dropped,
        request_count=page.request_count,
        scan_truncated=page.truncated,
    )


def _newest_first(rows: Sequence[CapitalFlowDto]) -> tuple[CapitalFlowDto, ...]:
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


async def fetch_capital_flows(
    client: BackstopClient, *, start_date: date, end_date: date
) -> CapitalFlowsFetchDto:
    """Walk subscriptions and redemptions for `start_date`..=`end_date` in two parallel calls."""
    subs, reds = await asyncio.gather(
        _walk(
            client,
            _SUBS_PATH,
            include="fundAccount.owner",
            start_date=start_date,
            end_date=end_date,
            kind="subscription",
        ),
        _walk(
            client,
            _REDS_PATH,
            include="originalSubscription.fundAccount",
            start_date=start_date,
            end_date=end_date,
            kind="redemption",
        ),
    )
    return CapitalFlowsFetchDto(
        rows=_newest_first((*subs.rows, *reds.rows)),
        rows_dropped=subs.non_actuals_dropped + reds.non_actuals_dropped,
        request_count=subs.request_count + reds.request_count,
        scan_truncated=subs.scan_truncated or reds.scan_truncated,
    )
