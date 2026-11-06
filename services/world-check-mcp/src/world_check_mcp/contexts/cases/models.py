from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class CaseDetails(BaseModel):
    case_id: str | None = Field(
        description="Client-provided external case ID, if the case has one."
    )
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")
    name: str = Field(description="Screened entity name.")
    entity_type: str = Field(description="Entity type, INDIVIDUAL or ORGANISATION.")
    group_id: str = Field(description="ID of the group that owns the case.")
    provider_types: list[str] = Field(
        description="Screening providers on the case, e.g. WATCHLIST."
    )
    lifecycle_state: str | None = Field(
        default=None, description="Case lifecycle state, e.g. UNARCHIVED."
    )


class CaseReferenceDetails(BaseModel):
    case_id: str = Field(description="Client-provided external case ID.")
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")


SearchMode = Literal["DEFAULT", "BEGINS_WITH", "EXACT", "CONTAINS"]


class CaseSummary(BaseModel):
    case_id: str | None = Field(
        description="Client-provided external case ID, if the case has one."
    )
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")
    name: str | None = Field(description="Screened entity name.")
    entity_type: str | None = Field(description="Entity type, INDIVIDUAL or ORGANISATION.")
    group_id: str | None = Field(description="ID of the group that owns the case.")
    lifecycle_state: str | None = Field(description="Case lifecycle state, e.g. UNARCHIVED.")


class CasePage(BaseModel):
    cases: list[CaseSummary] = Field(description="Cases on this page, newest first.")
    next_page: str | None = Field(
        description="Cursor for the next page, or null when there is none."
    )


class Match(BaseModel):
    result_id: str | None = Field(description="ID of the result within the case.")
    reference_id: str | None = Field(
        description="World-Check record reference ID, for get_profile."
    )
    provider_type: str | None = Field(
        description="Provider that produced the match, e.g. WATCHLIST."
    )
    match_strength: str | None = Field(description="Match strength, e.g. EXACT or WEAK.")
    submitted_term: str | None = Field(description="Submitted term that produced the match.")


class CaseResults(BaseModel):
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")
    matches: list[Match] = Field(description="Matches on this page.")
    next_page: str | None = Field(
        description="Cursor for the next page, or null when there is none."
    )


class ProviderSummary(BaseModel):
    provider_type: str = Field(description="Screening provider, e.g. WATCHLIST.")
    total_matches: int | None = Field(description="Total matches for the provider.")
    review_required: int | None = Field(description="Number of matches that require review.")
    unresolved: int | None = Field(description="Number of unresolved matches.")


class ScreeningStatus(BaseModel):
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")
    screening_status: str | None = Field(
        description="Overall screening status, or null when the case has not been screened."
    )
    providers: list[ProviderSummary] = Field(description="Per-provider screening summaries.")


class AuditEvent(BaseModel):
    id: str | None = Field(description="Audit event ID.")
    action_type: str | None = Field(description="Action recorded, e.g. SCREENED_CASE or NEW_CASE.")
    event_date: str | None = Field(description="Event timestamp (ISO 8601).")
    actioned_by: str | None = Field(description="Name of the user who performed the action.")


class AuditPage(BaseModel):
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")
    events: list[AuditEvent] = Field(description="Audit events on this page, newest first.")
    next_page: str | None = Field(
        description="Cursor for the next page, or null when there is none."
    )
