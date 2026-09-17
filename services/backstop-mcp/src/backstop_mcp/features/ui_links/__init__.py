"""CRM UI link grammar: build and parse Backstop `.action` / `activities.jsp` URLs.

No HTTP. Callers pass an already-resolved UI origin (`BackstopConfig.effective_ui_base_url`).
When that origin is missing, the builder returns a structured miss rather than guessing a host.
"""

from backstop_mcp.features.ui_links.activity_kinds import (
    ACTIVITY_JSP_SLUG_TO_KIND,
    ACTIVITY_KINDS,
    TARGET_KIND_TO_JSP_SLUG,
    ActivityKindMapping,
    activity_link_target,
)
from backstop_mcp.features.ui_links.dependencies import (
    get_build_entity_link_util_factory,
    get_parse_entity_link_util_factory,
    record_url,
)
from backstop_mcp.features.ui_links.entity_types import (
    PAGE_SPECS,
    BackstopUiPage,
    UiPageSpec,
)
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
from backstop_mcp.features.ui_links.responses import (
    BackstopLinkResponse,
    BackstopLinksResponse,
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
    "AccountLinkTarget",
    "ActivityKindMapping",
    "activity_link_target",
    "BackstopLinkResponse",
    "BackstopLinkTarget",
    "BackstopLinksResponse",
    "BackstopUiPage",
    "BuildEntityLinkResult",
    "BuildEntityLinkUtil",
    "CallLinkTarget",
    "DocumentLinkTarget",
    "EmailLinkTarget",
    "MeetingLinkTarget",
    "NoteLinkTarget",
    "OpportunityLinkTarget",
    "OrganizationLinkTarget",
    "ParseEntityLinkResult",
    "ParseEntityLinkUtil",
    "ParsedBackstopLinkResponse",
    "PersonLinkTarget",
    "ProductLinkTarget",
    "TaskLinkTarget",
    "UiBaseUrlNotConfiguredResponse",
    "UiPageSpec",
    "UnrecognizedBackstopUrlResponse",
    "get_build_entity_link_util_factory",
    "get_parse_entity_link_util_factory",
    "record_url",
]
