"""CRM UI link grammar: build and parse Backstop `.action` / `activities.jsp` URLs.

No HTTP. Callers pass an already-resolved UI origin (`BackstopConfig.effective_ui_base_url`).
When that origin is missing, the builder returns a structured miss rather than guessing a host.
"""

from backstop_mcp.features.ui_links.activity_kinds import (
    ACTIVITY_JSP_SLUG_TO_KIND,
    ACTIVITY_KINDS,
    TARGET_KIND_TO_JSP_SLUG,
    ActivityKindMapping,
)
from backstop_mcp.features.ui_links.entity_types import (
    PAGE_SPECS,
    BackstopUiPage,
    UiPageSpec,
)
from backstop_mcp.features.ui_links.internal_dto import (
    AccountLinkTargetDto,
    BackstopLinkTargetDto,
    CallLinkTargetDto,
    DocumentLinkTargetDto,
    EmailLinkTargetDto,
    MeetingLinkTargetDto,
    NoteLinkTargetDto,
    OpportunityLinkTargetDto,
    OrganizationLinkTargetDto,
    PersonLinkTargetDto,
    ProductLinkTargetDto,
    TaskLinkTargetDto,
)
from backstop_mcp.features.ui_links.responses import (
    BackstopLabeledUrlResponse,
    BackstopLinkResponse,
    BuildEntityLinkResult,
    ParsedBackstopLinkResponse,
    ParseEntityLinkResult,
    UiBaseUrlNotConfiguredResponse,
    UnrecognizedBackstopUrlResponse,
)
from backstop_mcp.features.ui_links.utils import BuildEntityLinkUtil, ParseEntityLinkUtil

__all__ = [
    "ACTIVITY_JSP_SLUG_TO_KIND",
    "ACTIVITY_KINDS",
    "PAGE_SPECS",
    "TARGET_KIND_TO_JSP_SLUG",
    "AccountLinkTargetDto",
    "ActivityKindMapping",
    "BackstopLabeledUrlResponse",
    "BackstopLinkResponse",
    "BackstopLinkTargetDto",
    "BackstopUiPage",
    "BuildEntityLinkResult",
    "BuildEntityLinkUtil",
    "CallLinkTargetDto",
    "DocumentLinkTargetDto",
    "EmailLinkTargetDto",
    "MeetingLinkTargetDto",
    "NoteLinkTargetDto",
    "OpportunityLinkTargetDto",
    "OrganizationLinkTargetDto",
    "ParseEntityLinkResult",
    "ParseEntityLinkUtil",
    "ParsedBackstopLinkResponse",
    "PersonLinkTargetDto",
    "ProductLinkTargetDto",
    "TaskLinkTargetDto",
    "UiBaseUrlNotConfiguredResponse",
    "UiPageSpec",
    "UnrecognizedBackstopUrlResponse",
]
