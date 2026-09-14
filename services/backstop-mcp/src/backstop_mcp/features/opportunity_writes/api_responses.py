"""Write-side wire shapes for opportunity PATCH and bulk stage-history POST.

`BulkLoadSummaryAttributes` is the only part of a bulk `201` that says whether anything
was written — HTTP status is always success. The document `id` is `null`; landed rows
are `attributes.records`.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.lenient import LenientInt, LenientStr

__all__ = [
    "BulkLoadErrorMessageAttributes",
    "BulkLoadSummaryAttributes",
    "BulkOpportunityStageHistoryAttributes",
    "BulkOpportunityStageHistoryDocument",
    "BulkOpportunityStageHistoryRecordAttributes",
    "BulkResourcePointerAttributes",
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


class BulkResourcePointerAttributes(BaseModel):
    """`{resourceId, resourceType}` on a landed history row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    resource_id: LenientStr = Field(default=None, validation_alias="resourceId")
    resource_type: LenientStr = Field(default=None, validation_alias="resourceType")


class BulkOpportunityStageHistoryRecordAttributes(BaseModel):
    """One row Backstop actually wrote. Failed request rows are omitted."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    id: LenientStr = None
    effective_date: LenientStr = Field(default=None, validation_alias="effectiveDate")
    opportunity: BulkResourcePointerAttributes | None = None
    stage: BulkResourcePointerAttributes | None = None


class BulkOpportunityStageHistoryAttributes(BaseModel):
    """Attributes on `POST /bulk-opportunity-stage-history`. Summary is nested."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    records: list[BulkOpportunityStageHistoryRecordAttributes] = Field(default_factory=list)
    bulk_load_summary: BulkLoadSummaryAttributes | None = Field(
        default=None, validation_alias="bulkLoadSummary"
    )

    def summary(self) -> BulkLoadSummaryAttributes:
        return self.bulk_load_summary or BulkLoadSummaryAttributes()


class BulkOpportunityStageHistoryResource(BaseModel):
    """Primary resource of a bulk `201`. `id` is `null` on this instance."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: str | None = None
    type: str
    attributes: BulkOpportunityStageHistoryAttributes


class BulkOpportunityStageHistoryDocument(BaseModel):
    """The `201` envelope. Not `BackstopApiSingleResourceDocument` — that requires an id."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    data: BulkOpportunityStageHistoryResource
    included: list[dict[str, object]] = Field(default_factory=list)
