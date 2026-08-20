"""Group scanned entity-activities rows so a counting question never pays for row bodies."""

from collections import Counter
from collections.abc import Sequence
from typing import Literal

from backstop_mcp.features.activity_history.internal_dto import EntityActivityDto
from backstop_mcp.features.collection_scan import AggregateBucketDto

__all__ = ["aggregate_entity_activities"]

ActivityAggregateBy = Literal["type", "tag", "party", "period"]

_UNTAGGED = "(untagged)"
_UNATTRIBUTED = "(unattributed)"
_UNDATED = "(undated)"
_UNKNOWN = "(unknown)"


def aggregate_entity_activities(
    rows: Sequence[EntityActivityDto], *, group_by: ActivityAggregateBy
) -> tuple[AggregateBucketDto, ...]:
    counts: Counter[tuple[str, str]] = Counter()
    if group_by == "type":
        for row in rows:
            key = row.type or _UNKNOWN
            counts[(key, key)] += 1
    elif group_by == "tag":
        for row in rows:
            if not row.tags:
                counts[(_UNTAGGED, _UNTAGGED)] += 1
                continue
            for tag in row.tags:
                counts[(tag.id, tag.name)] += 1
    elif group_by == "party":
        for row in rows:
            if not row.associated_with:
                counts[(_UNATTRIBUTED, _UNATTRIBUTED)] += 1
                continue
            for party in row.associated_with:
                label = party.resource_type or party.id
                counts[(party.id, f"{label}:{party.id}")] += 1
    else:
        for row in rows:
            if row.effective_date is None:
                counts[(_UNDATED, _UNDATED)] += 1
                continue
            period = row.effective_date.strftime("%Y-%m")
            counts[(period, period)] += 1
    return tuple(
        AggregateBucketDto(key=key, label=label, count=count)
        for (key, label), count in counts.most_common()
    )
