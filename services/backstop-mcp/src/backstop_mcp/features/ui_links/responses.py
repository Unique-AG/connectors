"""Published builder and parser results. Misses are structured models, not exceptions."""

from typing import Literal, Self

from pydantic import BaseModel, Field

from backstop_mcp.features.ui_links.entity_types import BackstopUiPage
from backstop_mcp.features.ui_links.inputs import BackstopLinkTarget
from backstop_mcp.features.ui_links.internal_dto import BackstopLinkTargetDto


class BackstopLinkResponse(BaseModel):
    """One labeled CRM UI URL."""

    label: str = Field(description="Tab, layout, or canonical label for this URL.")
    url: str = Field(description="Absolute CRM UI URL. Echo it; never invent one.")


class BackstopLinksResponse(BaseModel):
    """Labeled CRM UI URLs for one target."""

    status: Literal["ok"] = Field(
        default="ok",
        description="Links were built. `links` may still be empty if no tab matched.",
    )
    links: list[BackstopLinkResponse] = Field(
        description="Labeled URLs for the requested tabs and optional layout."
    )


class UiBaseUrlNotConfiguredResponse(BaseModel):
    """This deployment has no CRM UI origin, so no links can be built."""

    status: Literal["not_configured"] = Field(
        default="not_configured",
        description=(
            "Always 'not_configured': BACKSTOP_UI_BASE_URL is unset and no fallback applies."
        ),
    )
    message: str = Field(
        default="UI base URL is not configured for this deployment",
        description="Operator-facing reason. Do not invent a host.",
    )


class ParsedBackstopLinkResponse(BaseModel):
    """A recognized Backstop CRM UI URL, split into page, id, tab, and layout."""

    status: Literal["ok"] = Field(
        default="ok",
        description="The URL matched a known Backstop UI page and carried a recognizable id.",
    )
    page: BackstopUiPage = Field(description="CRM UI page the path matched.")
    entity_kind: str | None = Field(
        default=None,
        description=(
            "Target kind (organization, person, account, product, opportunity, task, "
            "email, call, meeting, note, document). Omitted for LandingPageUrl."
        ),
    )
    entity_id: str = Field(description="Id the URL points at. Echo it; never invent one.")
    tab: str | None = Field(
        default=None,
        description=(
            "Tab query value (`viewType` or `acctViewType`). Omitted when the URL has no tab. "
            "Product summary is omission — this is None, not 'summary'."
        ),
    )
    layout_name: str | None = Field(
        default=None,
        description="`layoutName` when the URL is a layout link.",
    )
    view_entity_type: str | None = Field(
        default=None,
        description="`viewEntityType` Bean when the URL is a layout link.",
    )
    resource_type: str | None = Field(
        default=None,
        description="`resourceType` on LandingPageUrl.action. Omitted on other pages.",
    )
    view_only: bool | None = Field(
        default=None,
        description="`viewOnly` on a task URL when present. Not required to recognize the page.",
    )
    workflow_task_id: str | None = Field(
        default=None,
        description="`workflowTaskId` on a task URL when the param is present, including empty.",
    )
    host_mismatch: bool = Field(
        description=(
            "True when a configured UI base URL was given and the pasted host differs. "
            "The URL is still parsed."
        ),
    )
    suggested_tool: str | None = Field(
        default=None,
        description=(
            "MCP tool that can load this record from the parsed id, when one exists. "
            "Omitted when none does; read suggested_note before calling a party-scoped tool."
        ),
    )
    suggested_note: str | None = Field(
        default=None,
        description=(
            "Caveat for the suggested tool or for why none exists "
            "(e.g. an account id is not a party id)."
        ),
    )

    @classmethod
    def from_dto(
        cls,
        dto: BackstopLinkTargetDto,
        *,
        host_mismatch: bool,
        suggested_tool: str | None,
        suggested_note: str | None,
    ) -> Self:
        return cls(
            page=dto.page,
            entity_kind=dto.entity_kind,
            entity_id=dto.entity_id,
            tab=dto.tab,
            layout_name=dto.layout_name,
            view_entity_type=dto.view_entity_type,
            resource_type=dto.resource_type,
            view_only=dto.view_only,
            workflow_task_id=dto.workflow_task_id,
            host_mismatch=host_mismatch,
            suggested_tool=suggested_tool,
            suggested_note=suggested_note,
        )

    def to_target(self) -> BackstopLinkTarget | None:
        """Rebuild the published target. LandingPageUrl has no buildable target."""
        return BackstopLinkTargetDto(
            page=self.page,
            entity_id=self.entity_id,
            entity_kind=self.entity_kind,
        ).to_input()


class UnrecognizedBackstopUrlResponse(BaseModel):
    """The pasted string is not a Backstop CRM UI URL this feature can read."""

    status: Literal["unrecognized"] = Field(
        default="unrecognized",
        description="Always 'unrecognized': the URL did not match a known page and id.",
    )
    message: str = Field(
        default="unrecognized Backstop URL",
        description="Why the URL was rejected. Do not invent a target from it.",
    )


type BuildEntityLinkResult = BackstopLinksResponse | UiBaseUrlNotConfiguredResponse
type ParseEntityLinkResult = ParsedBackstopLinkResponse | UnrecognizedBackstopUrlResponse
