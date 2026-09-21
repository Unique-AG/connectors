"""Published discriminated link target. Each kind names its own id so a mix-up cannot build.

Email uses `entity_activity_details_id` (the `/entity-activity-details` id). It does
not accept `activity_id` — that name is an `/emails` collection id on history rows.
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
            "Account id from get_accounts_for_party. This is not a party id — do not pass it "
            "to get_organization or get_person."
        ),
    )


class ProductLinkTarget(BaseModel):
    kind: Literal["product"] = Field(
        default="product",
        description="Product CRM page. Echo a product id from get_product.",
    )
    entity_id: CoercedId = Field(
        description="Product id from get_product. Not a party id.",
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
            "Email CRM page. Requires entity_activity_details_id from search_activities or "
            "get_activity_detail. An email activity_id from get_activity_history is a "
            "different id space and will not open this page."
        ),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Id from search_activities or get_activity_detail (`entity_activity_details_id`). "
            "Never a get_activity_history email activity_id — those id spaces do not match."
        ),
    )


class CallLinkTarget(BaseModel):
    kind: Literal["call"] = Field(
        default="call",
        description=(
            "Call CRM page (`activities.jsp/calls`). Echo entity_activity_details_id from "
            "search_activities or get_activity_detail."
        ),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Id from search_activities or get_activity_detail (`entity_activity_details_id`). "
            "Not a get_activity_history activity_id."
        ),
    )


class MeetingLinkTarget(BaseModel):
    kind: Literal["meeting"] = Field(
        default="meeting",
        description=(
            "Meeting CRM page (`activities.jsp/meetings`). Echo entity_activity_details_id "
            "from search_activities or get_activity_detail."
        ),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Id from search_activities or get_activity_detail (`entity_activity_details_id`). "
            "Not a get_activity_history activity_id."
        ),
    )


class NoteLinkTarget(BaseModel):
    kind: Literal["note"] = Field(
        default="note",
        description=(
            "Note CRM page (`activities.jsp/notes`). Echo entity_activity_details_id from "
            "search_activities or get_activity_detail."
        ),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Id from search_activities or get_activity_detail (`entity_activity_details_id`). "
            "Not a get_activity_history activity_id."
        ),
    )


class DocumentLinkTarget(BaseModel):
    kind: Literal["document"] = Field(
        default="document",
        description=(
            "Document CRM page (`activities.jsp/documents`). Echo entity_activity_details_id "
            "from search_activities or get_activity_detail."
        ),
    )
    entity_activity_details_id: CoercedId = Field(
        description=(
            "Id from search_activities or get_activity_detail (`entity_activity_details_id`). "
            "Not a get_activity_history activity_id."
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
