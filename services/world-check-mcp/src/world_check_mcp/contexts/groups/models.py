from pydantic import BaseModel
from pydantic import Field


class Group(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    child_groups: list[Group] = Field(default_factory=list)


class SecondaryField(BaseModel):
    provider: str
    entity_type: str
    type_id: str
    label: str
    value_type: str
    required: bool


class ResolutionOption(BaseModel):
    id: str
    label: str
    status_type: str | None = None


class ResolutionToolkit(BaseModel):
    provider_type: str
    statuses: list[ResolutionOption]
    risks: list[ResolutionOption]
    reasons: list[ResolutionOption]


class GroupSettings(BaseModel):
    group: Group
    screening_type: str
    mandatory_provider_types: list[str]
    secondary_fields: list[SecondaryField]
    toolkits: list[ResolutionToolkit]
