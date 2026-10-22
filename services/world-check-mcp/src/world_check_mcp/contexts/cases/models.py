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
