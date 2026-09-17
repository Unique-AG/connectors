"""Discriminated link targets. Each kind names its own id so a mix-up cannot build.

Email uses `entity_activity_details_id` (the `/entity-activity-details` id). It does
not accept `activity_id` — that name is an `/emails` collection id on history rows.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backstop_mcp.models import CoercedId


class OrganizationLinkTargetDto(BaseModel):
    kind: Literal["organization"] = "organization"
    party_id: CoercedId


class PersonLinkTargetDto(BaseModel):
    kind: Literal["person"] = "person"
    party_id: CoercedId


class AccountLinkTargetDto(BaseModel):
    kind: Literal["account"] = "account"
    entity_id: CoercedId


class ProductLinkTargetDto(BaseModel):
    kind: Literal["product"] = "product"
    entity_id: CoercedId


class OpportunityLinkTargetDto(BaseModel):
    kind: Literal["opportunity"] = "opportunity"
    entity_id: CoercedId


class TaskLinkTargetDto(BaseModel):
    kind: Literal["task"] = "task"
    task_id: CoercedId


class EmailLinkTargetDto(BaseModel):
    kind: Literal["email"] = "email"
    entity_activity_details_id: CoercedId


class CallLinkTargetDto(BaseModel):
    kind: Literal["call"] = "call"
    entity_activity_details_id: CoercedId


class MeetingLinkTargetDto(BaseModel):
    kind: Literal["meeting"] = "meeting"
    entity_activity_details_id: CoercedId


class NoteLinkTargetDto(BaseModel):
    kind: Literal["note"] = "note"
    entity_activity_details_id: CoercedId


class DocumentLinkTargetDto(BaseModel):
    kind: Literal["document"] = "document"
    entity_activity_details_id: CoercedId


BackstopLinkTargetDto = Annotated[
    OrganizationLinkTargetDto
    | PersonLinkTargetDto
    | AccountLinkTargetDto
    | ProductLinkTargetDto
    | OpportunityLinkTargetDto
    | TaskLinkTargetDto
    | EmailLinkTargetDto
    | CallLinkTargetDto
    | MeetingLinkTargetDto
    | NoteLinkTargetDto
    | DocumentLinkTargetDto,
    Field(discriminator="kind"),
]
