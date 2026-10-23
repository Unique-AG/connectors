from typing import ClassVar

from mcp_openapi.upstream import Operation
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import TypeAdapter


class PageReferencesWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    next: str | None = None


class PaginationWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    page_references: PageReferencesWire | None = Field(default=None, alias="pageReferences")


class CaseHitWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    case_id: str | None = Field(default=None, alias="caseId")
    case_system_id: str | None = Field(default=None, alias="caseSystemId")
    name: str | None = None
    entity_type: str | None = Field(default=None, alias="entityType")
    group_id: str | None = Field(default=None, alias="groupId")
    lifecycle_state: str | None = Field(default=None, alias="lifecycleState")


class CaseSearchWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    results: list[CaseHitWire] = []
    pagination: PaginationWire | None = None


class ResultWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    result_id: str | None = Field(default=None, alias="resultId")
    reference_id: str | None = Field(default=None, alias="referenceId")
    provider_type: str | None = Field(default=None, alias="providerType")
    match_strength: str | None = Field(default=None, alias="matchStrength")
    submitted_term: str | None = Field(default=None, alias="submittedTerm")


class ResultsWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    results: list[ResultWire] = []
    pagination: PaginationWire | None = None


class ProviderCountWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    total_matches: int | None = Field(default=None, alias="totalMatches")
    review_required: int | None = Field(default=None, alias="reviewRequired")
    unresolved: int | None = None


class ScreeningStatusWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    case_system_id: str = Field(alias="caseSystemId")
    screening_status: str | None = Field(default=None, alias="screeningStatus")
    provider_summaries: dict[str, ProviderCountWire] = Field(
        default_factory=dict, alias="providerSummaries"
    )


class AuditEventWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    action_type: str | None = Field(default=None, alias="actionType")
    event_date: str | None = Field(default=None, alias="eventDate")
    actioned_by_user_name: str | None = Field(default=None, alias="actionedByUserName")


class AuditSearchWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    results: list[AuditEventWire] = []
    pagination: PaginationWire | None = None


SEARCH_CASES = Operation[CaseSearchWire]("searchCases", TypeAdapter(CaseSearchWire))
GET_RESULTS = Operation[ResultsWire]("getResults", TypeAdapter(ResultsWire))
GET_SCREENING_STATUS = Operation[list[ScreeningStatusWire]](
    "getScreeningStatus", TypeAdapter(list[ScreeningStatusWire])
)
GET_CASE_AUDIT_EVENTS = Operation[AuditSearchWire](
    "getCaseAuditEventsByCaseSystemId", TypeAdapter(AuditSearchWire)
)


def next_page(pagination: PaginationWire | None) -> str | None:
    if pagination is None or pagination.page_references is None:
        return None
    reference = pagination.page_references.next
    return reference or None
