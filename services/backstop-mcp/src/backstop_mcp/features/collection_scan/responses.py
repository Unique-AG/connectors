from typing import ClassVar, Self

from pydantic import ConfigDict, Field

from backstop_mcp.features.collection_scan.internal_dto import AggregateBucketDto
from backstop_mcp.models import OmitNoneModel

__all__ = ["AggregateBucketResponse", "ScanCoverageResponse"]


class ScanCoverageResponse(OmitNoneModel):
    """How much of the matching set this call actually saw."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rows_scanned: int = Field(
        description=(
            "How many result rows the collection sent across the pages this call fetched, "
            "including rows dropped as unreadable."
        )
    )
    visible_count: int | None = Field(
        default=None,
        description=(
            "The collection's own total for this query — records visible to you with this "
            "credential, not a firm-wide fact. Two users can ask the same question and get "
            "different totals. Omitted when no count was sent."
        ),
    )
    visible_count_is_floor: bool = Field(
        description=(
            "True when `visible_count` equals the endpoint ceiling. That figure is a floor, "
            "not a count — the true total is unknown."
        )
    )
    truncated: bool = Field(
        description=(
            "True when this payload is not the full visible set: the row cap fired, the "
            "ceiling was hit, or a later page failed."
        )
    )
    ceiling_hit: bool = Field(
        description=(
            "True when the next page would have exceeded the endpoint ceiling, or "
            "`visible_count` is already that ceiling. Narrow the window; do not retry the "
            "same query."
        )
    )
    partial_due_to_error: bool = Field(
        description=(
            "True when a later page failed after some rows had already been read. This is a "
            "partial scan, not a complete count — do not treat aggregates as the full set."
        )
    )
    rows_dropped: int = Field(
        description=(
            "How many result rows could not be read and were omitted rather than failing the call."
        )
    )
    disclaimer: str | None = Field(
        default=None,
        description=(
            "Set when truncated, the ceiling was hit, or a later page failed. Relay this; "
            "do not hide it."
        ),
    )


class AggregateBucketResponse(OmitNoneModel):
    """One group in aggregate mode: the key, a label, and how many scanned rows fell in it."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str = Field(
        description="Stable identity of this bucket (type, tag id, party id, stage, or period)."
    )
    label: str = Field(description="Human-readable name for the bucket.")
    count: int = Field(
        description=(
            "How many scanned rows fell in this bucket, visible to you. A row with several "
            "tags or parties increments each of those buckets."
        )
    )

    @classmethod
    def from_dto(cls, bucket: AggregateBucketDto) -> Self:
        return cls(key=bucket.key, label=bucket.label, count=bucket.count)
