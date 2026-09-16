"""The part of a bulk `201` that says whether anything was written.

Every `POST /bulk-*` route answers a success status regardless of outcome; `bulkLoadSummary`
is the only place the truth is. Shared by every bulk writer — the shape is the route family's,
not one feature's.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.lenient import LenientInt, LenientStr

__all__ = [
    "BulkLoadErrorMessageAttributes",
    "BulkLoadSummaryAttributes",
]


class BulkLoadErrorMessageAttributes(BaseModel):
    """One per-record error from a bulk write. `index` is 0-based."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    index: LenientInt = None
    message: LenientStr = None


class BulkLoadSummaryAttributes(BaseModel):
    """`bulkLoadSummary` on a bulk POST. A `201` with `successCount: 0` is a total failure."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    total_count: LenientInt = Field(default=None, validation_alias="totalCount")
    success_count: LenientInt = Field(default=None, validation_alias="successCount")
    error_messages: list[BulkLoadErrorMessageAttributes] = Field(
        default_factory=list, validation_alias="errorMessages"
    )
