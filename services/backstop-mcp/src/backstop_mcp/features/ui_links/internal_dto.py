"""Normalized page + id the builder and parser share. Not published."""

from typing import Self

from pydantic import BaseModel

from backstop_mcp.features.ui_links.activity_kinds import TARGET_KIND_TO_JSP_SLUG
from backstop_mcp.features.ui_links.entity_types import BackstopUiPage
from backstop_mcp.features.ui_links.inputs import (
    AccountLinkTarget,
    BackstopLinkTarget,
    CallLinkTarget,
    DocumentLinkTarget,
    EmailLinkTarget,
    MeetingLinkTarget,
    NoteLinkTarget,
    OpportunityLinkTarget,
    OrganizationLinkTarget,
    PersonLinkTarget,
    ProductLinkTarget,
    TaskLinkTarget,
)


class BackstopLinkTargetDto(BaseModel):
    """One CRM page identity: page, id, optional tab/layout, and extra params."""

    page: BackstopUiPage
    entity_id: str
    entity_kind: str | None = None
    tab: str | None = None
    layout_name: str | None = None
    view_entity_type: str | None = None
    activity_slug: str | None = None
    resource_type: str | None = None
    view_only: bool | None = None
    workflow_task_id: str | None = None

    @classmethod
    def from_input(cls, target: BackstopLinkTarget) -> Self:
        match target.kind:
            case "organization":
                return cls(
                    page=BackstopUiPage.ORGANIZATION,
                    entity_id=target.party_id,
                    entity_kind="organization",
                )
            case "person":
                return cls(
                    page=BackstopUiPage.PERSON,
                    entity_id=target.party_id,
                    entity_kind="person",
                )
            case "account":
                return cls(
                    page=BackstopUiPage.ACCOUNT,
                    entity_id=target.entity_id,
                    entity_kind="account",
                )
            case "product":
                return cls(
                    page=BackstopUiPage.PRODUCT,
                    entity_id=target.entity_id,
                    entity_kind="product",
                )
            case "opportunity":
                return cls(
                    page=BackstopUiPage.OPPORTUNITY,
                    entity_id=target.entity_id,
                    entity_kind="opportunity",
                )
            case "task":
                return cls(
                    page=BackstopUiPage.TASK,
                    entity_id=target.task_id,
                    entity_kind="task",
                )
            case "email":
                return cls(
                    page=BackstopUiPage.EMAIL,
                    entity_id=target.entity_activity_details_id,
                    entity_kind="email",
                )
            case "call" | "meeting" | "note" | "document":
                return cls(
                    page=BackstopUiPage.ACTIVITY,
                    entity_id=target.entity_activity_details_id,
                    entity_kind=target.kind,
                    activity_slug=TARGET_KIND_TO_JSP_SLUG[target.kind],
                )

    def to_input(self) -> BackstopLinkTarget | None:
        entity_id = self.entity_id
        match self.entity_kind:
            case "organization":
                return OrganizationLinkTarget(party_id=entity_id)
            case "person":
                return PersonLinkTarget(party_id=entity_id)
            case "account":
                return AccountLinkTarget(entity_id=entity_id)
            case "product":
                return ProductLinkTarget(entity_id=entity_id)
            case "opportunity":
                return OpportunityLinkTarget(entity_id=entity_id)
            case "task":
                return TaskLinkTarget(task_id=entity_id)
            case "email":
                return EmailLinkTarget(entity_activity_details_id=entity_id)
            case "call":
                return CallLinkTarget(entity_activity_details_id=entity_id)
            case "meeting":
                return MeetingLinkTarget(entity_activity_details_id=entity_id)
            case "note":
                return NoteLinkTarget(entity_activity_details_id=entity_id)
            case "document":
                return DocumentLinkTarget(entity_activity_details_id=entity_id)
            case _:
                return None
