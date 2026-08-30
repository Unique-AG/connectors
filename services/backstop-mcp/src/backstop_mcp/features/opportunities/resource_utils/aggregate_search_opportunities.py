from collections import Counter
from collections.abc import Sequence
from datetime import date
from typing import Literal

from backstop_mcp.features.collection_scan import AggregateBucketDto
from backstop_mcp.features.opportunities.responses import SearchOpportunityRowResponse

__all__ = ["OpportunityGroupBy", "aggregate_search_opportunities"]

type OpportunityGroupBy = Literal["stage", "product", "period", "party"]

_UNKNOWN = "(unknown)"
_UNATTRIBUTED = "(unattributed)"
_UNDATED = "(undated)"


def _month_key(value: date | None) -> tuple[str, str]:
    if value is None:
        return (_UNDATED, _UNDATED)
    stamp = f"{value.year:04d}-{value.month:02d}"
    return (stamp, stamp)


def _bucket(row: SearchOpportunityRowResponse, group_by: OpportunityGroupBy) -> tuple[str, str]:
    match group_by:
        case "stage":
            if row.stage_id and row.stage:
                return (row.stage_id, row.stage)
            return (row.stage or row.stage_id or _UNKNOWN, row.stage or _UNKNOWN)
        case "product":
            if row.product is None:
                return (_UNATTRIBUTED, _UNATTRIBUTED)
            return (row.product.id, row.product.name or row.product.id)
        case "period":
            return _month_key(row.expected_investment_date or row.date_entered_current_stage)
        case "party":
            if row.investor is None:
                return (_UNATTRIBUTED, _UNATTRIBUTED)
            return (row.investor.id, row.investor.name or row.investor.id)


def aggregate_search_opportunities(
    rows: Sequence[SearchOpportunityRowResponse], *, group_by: OpportunityGroupBy
) -> tuple[AggregateBucketDto, ...]:
    """Count matching deals per `group_by` key, largest buckets first."""
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        counts[_bucket(row, group_by)] += 1
    return tuple(
        AggregateBucketDto(key=key, label=label, count=count)
        for (key, label), count in sorted(counts.items(), key=lambda item: (-item[1], item[0][1]))
    )
