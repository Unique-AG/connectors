from pydantic import BaseModel
from pydantic import Field


class Group(BaseModel):
    id: str = Field(description="Group ID.")
    name: str = Field(description="Group name.")
    parent_id: str | None = Field(default=None, description="Parent group ID, or null for a root.")
    child_groups: list[Group] = Field(
        default_factory=list, description="Direct child groups, nested."
    )


class SecondaryField(BaseModel):
    provider: str = Field(description="Provider the field applies to, e.g. watchlist.")
    entity_type: str = Field(description="Entity type the field applies to, e.g. individual.")
    type_id: str = Field(description="Field typeId, passed back in screening secondary fields.")
    label: str = Field(description="Human-readable field label, e.g. DATE_OF_BIRTH.")
    value_type: str = Field(description="Value type, e.g. DATE, COUNTRY, GENDER, or TEXT.")
    required: bool = Field(description="Whether the field is required when screening.")


class ResolutionOption(BaseModel):
    id: str = Field(description="Option ID, passed back when resolving a result.")
    label: str = Field(description="Human-readable option label.")
    status_type: str | None = Field(
        default=None, description="Status category, for a status option."
    )


class ResolutionToolkit(BaseModel):
    provider_type: str = Field(description="Provider the toolkit applies to, e.g. WATCHLIST.")
    statuses: list[ResolutionOption] = Field(description="Allowed resolution statuses.")
    risks: list[ResolutionOption] = Field(description="Allowed risk ratings.")
    reasons: list[ResolutionOption] = Field(description="Allowed resolution reasons.")


class GroupSettings(BaseModel):
    group: Group = Field(description="The group.")
    screening_type: str = Field(description="Group screening type, e.g. CASE_MANAGEMENT_AUDIT.")
    mandatory_provider_types: list[str] = Field(
        description="Providers that must be screened, e.g. WATCHLIST."
    )
    secondary_fields: list[SecondaryField] = Field(
        description="Secondary fields the group's cases accept."
    )
    toolkits: list[ResolutionToolkit] = Field(
        description="Resolution toolkits available for the group."
    )
