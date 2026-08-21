"""Subscriptions and redemptions for a mandatory transaction-date window.

Two calls: `/hedge-fund-account-subscriptions?include=fundAccount.owner` and
`/hedge-fund-account-redemptions?include=originalSubscription.fundAccount`. A redemption
has no `fundAccount` of its own — it reaches an account only through
`originalSubscription`. Missing that chain is reported as `unattributed`, not dropped.
`filter[transactionDate]` is mandatory; an unfiltered read is 400. Actuals only
(`status=COMPLETED`).
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Literal, cast

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopClient,
    IncludedResource,
    follow_included,
    included_resource,
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
)

logger = logging.getLogger(__name__)

_SUBS_PATH = "/hedge-fund-account-subscriptions"
_REDS_PATH = "/hedge-fund-account-redemptions"
_PAGE_SIZE = 200
_ACTUAL = "COMPLETED"
type FlowKind = Literal["subscription", "redemption"]
type FlowResource = BackstopApiResource[CapitalFlowAttributes]


def _included_by_ref(
    included: Sequence[dict[str, object]], ref: Mapping[str, object] | None
) -> dict[str, object] | None:
    if ref is None:
        return None
    ref_id, ref_type = ref.get("id"), ref.get("type")
    if not isinstance(ref_id, str) or not isinstance(ref_type, str):
        return None
    for item in included:
        if item.get("id") == ref_id and item.get("type") == ref_type:
            return item
    return None


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
    resource: FlowResource, included: Sequence[dict[str, object]]
) -> tuple[CapitalFlowPartyDto | None, CapitalFlowPartyDto | None]:
    accounts = follow_included(included, resource, "fundAccount")
    account_raw = accounts[0] if accounts else None
    owner_raw = _included_by_ref(included, _relationship_data(account_raw or {}, "owner"))
    return _account_chip(account_raw), _owner_chip(owner_raw)


def _redemption_attribution(
    resource: FlowResource, included: Sequence[dict[str, object]]
) -> tuple[CapitalFlowPartyDto | None, CapitalFlowPartyDto | None]:
    originals = follow_included(included, resource, "originalSubscription")
    if not originals:
        return None, None
    account_raw = _included_by_ref(included, _relationship_data(originals[0], "fundAccount"))
    owner_raw = _included_by_ref(included, _relationship_data(account_raw or {}, "owner"))
    return _account_chip(account_raw), _owner_chip(owner_raw)


def _project_row(
    resource: FlowResource,
    *,
    kind: FlowKind,
    included: Sequence[dict[str, object]],
) -> CapitalFlowDto | None:
    attributes = resource.attributes
    if (attributes.status or "").upper() != _ACTUAL:
        return None
    if kind == "subscription":
        account, owner = _subscription_attribution(resource, included)
    else:
        account, owner = _redemption_attribution(resource, included)
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
) -> tuple[tuple[CapitalFlowDto, ...], int]:
    page = await client.paginate(
        path,
        schema=BackstopApiResource[CapitalFlowAttributes],
        params={**_date_params(start_date=start_date, end_date=end_date), "include": include},
        max_records=None,
        page_size=_PAGE_SIZE,
        parallel=True,
    )
    rows: list[CapitalFlowDto] = []
    for resource in page.items:
        projected = _project_row(resource, kind=kind, included=page.included)
        if projected is None:
            continue
        rows.append(projected)
    return tuple(rows), 0


async def fetch_capital_flows(
    client: BackstopClient, *, start_date: date, end_date: date
) -> CapitalFlowsFetchDto:
    """Walk subscriptions and redemptions for `start_date`..=`end_date` in two parallel calls."""
    (subs, subs_dropped), (reds, reds_dropped) = await asyncio.gather(
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
    merged = sorted(
        (*subs, *reds),
        key=lambda row: (row.transaction_date is None, row.transaction_date),
        reverse=True,
    )
    return CapitalFlowsFetchDto(
        rows=tuple(merged),
        rows_dropped=subs_dropped + reds_dropped,
        request_count=2,
    )
