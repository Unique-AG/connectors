"""Published discriminated link target. Each kind names its own id so a mix-up cannot build.

Activity links take the bare `id` of a `search_activities` row. Never a
`meeting-or-calls_…` handle. Rows already carry `url` when that field is selected.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backstop_mcp.models import CoercedId


class OrganizationLinkTarget(BaseModel):
    kind: Literal["organization"] = Field(
        default="organization",
        description=(
            "Organization CRM page. Echo a party id from get_organization or a prior resolve; "
            "never an account id."
        ),
    )
    party_id: CoercedId = Field(
        description=(
            "Organization party id from get_organization or a resolve echo. Not an account id "
            "and not an entity_id."
        ),
    )


class PersonLinkTarget(BaseModel):
    kind: Literal["person"] = Field(
        default="person",
        description=(
            "Person CRM page. Echo a party id from get_person or a prior resolve; never an "
            "account id."
        ),
    )
    party_id: CoercedId = Field(
        description=(
            "Person party id from get_person or a resolve echo. Not an account id and not an "
            "entity_id."
        ),
    )


class AccountLinkTarget(BaseModel):
    kind: Literal["account"] = Field(
        default="account",
        description="Account CRM page. Uses an account id, which is not a party id.",
    )
    entity_id: CoercedId = Field(
        description=(
            "Account id, not a party id. No tool loads the account record; the id goes to "
            "get_time_series (entity_type accounts) or get_capital_flows `account_ids`."
        ),
    )


class ProductLinkTarget(BaseModel):
    kind: Literal["product"] = Field(
        default="product",
        description="Product CRM page. Echo a product id from search_products.",
    )
    entity_id: CoercedId = Field(
        description="Product id from search_products. Not a party id.",
    )


class OpportunityLinkTarget(BaseModel):
    kind: Literal["opportunity"] = Field(
        default="opportunity",
        description="Opportunity CRM page. Echo an opportunity id from get_opportunities.",
    )
    entity_id: CoercedId = Field(
        description="Opportunity id from get_opportunities or get_opportunities_by_ids.",
    )


class TaskLinkTarget(BaseModel):
    kind: Literal["task"] = Field(
        default="task",
        description="Task CRM page. Echo a task id; no MCP tool loads a task by id.",
    )
    task_id: CoercedId = Field(
        description="Task id from get_tasks_for_party. This is a taskId, not a party id.",
    )


class EmailLinkTarget(BaseModel):
    kind: Literal["email"] = Field(
        default="email",
        description=(
            "Email CRM page. Pass the bare `id` of a `search_activities` row. Never a "
            "`meeting-or-calls_…` handle, and never a history email `activity_id`."
        ),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Bare `id` of a `search_activities` email row. Never a history email "
            "`activity_id` and never a `meeting-or-calls_…` handle."
        ),
    )


class CallLinkTarget(BaseModel):
    kind: Literal["call"] = Field(
        default="call",
        description=("Call CRM page. Pass the bare `id` of a `search_activities` row."),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Bare `id` of a `search_activities` row. Never a `meeting-or-calls_…` handle."
        ),
    )


class MeetingLinkTarget(BaseModel):
    kind: Literal["meeting"] = Field(
        default="meeting",
        description=("Meeting CRM page. Pass the bare `id` of a `search_activities` row."),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Bare `id` of a `search_activities` row. Never a `meeting-or-calls_…` handle."
        ),
    )


class NoteLinkTarget(BaseModel):
    kind: Literal["note"] = Field(
        default="note",
        description=("Note CRM page. Pass the bare `id` of a `search_activities` row."),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Bare `id` of a `search_activities` row. Never a `meeting-or-calls_…` handle."
        ),
    )


class DocumentLinkTarget(BaseModel):
    kind: Literal["document"] = Field(
        default="document",
        description=("Document CRM page. Pass the bare `id` of a `search_activities` row."),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Bare `id` of a `search_activities` row. Never a `meeting-or-calls_…` handle."
        ),
    )


BackstopLinkTarget = Annotated[
    OrganizationLinkTarget
    | PersonLinkTarget
    | AccountLinkTarget
    | ProductLinkTarget
    | OpportunityLinkTarget
    | TaskLinkTarget
    | EmailLinkTarget
    | CallLinkTarget
    | MeetingLinkTarget
    | NoteLinkTarget
    | DocumentLinkTarget,
    Field(discriminator="kind"),
]
