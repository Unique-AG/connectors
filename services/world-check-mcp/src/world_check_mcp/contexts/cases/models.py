from typing import Literal

from pydantic import BaseModel


class CaseDetails(BaseModel):
    case_id: str | None
    case_system_id: str
    name: str
    entity_type: str
    group_id: str
    provider_types: list[str]
    lifecycle_state: str | None = None


class CaseReferenceDetails(BaseModel):
    case_id: str
    case_system_id: str


SearchMode = Literal["DEFAULT", "BEGINS_WITH", "EXACT", "CONTAINS"]


class CaseSummary(BaseModel):
    case_id: str | None
    case_system_id: str
    name: str | None
    entity_type: str | None
    group_id: str | None
    lifecycle_state: str | None


class CasePage(BaseModel):
    cases: list[CaseSummary]
    next_page: str | None


class Match(BaseModel):
    result_id: str | None
    reference_id: str | None
    provider_type: str | None
    match_strength: str | None
    submitted_term: str | None


class CaseResults(BaseModel):
    case_system_id: str
    matches: list[Match]
    next_page: str | None


class ProviderSummary(BaseModel):
    provider_type: str
    total_matches: int | None
    review_required: int | None
    unresolved: int | None


class ScreeningStatus(BaseModel):
    case_system_id: str
    screening_status: str | None
    providers: list[ProviderSummary]


class AuditEvent(BaseModel):
    id: str | None
    action_type: str | None
    event_date: str | None
    actioned_by: str | None


class AuditPage(BaseModel):
    case_system_id: str
    events: list[AuditEvent]
    next_page: str | None
