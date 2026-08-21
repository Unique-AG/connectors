"""The `?include=` allowlist: which related records a read tool can side-load, and their shape.

The includes models (`OrganizationIncludesResponse`, `PersonIncludesResponse`,
`ActivityIncludesResponse`) *are* the allowlist: one field per exposed include, carrying its
Backstop `Include` as field metadata and its projected shape as its annotation. `include_plan`
reads a model and the names requested of it into an `IncludePlan` — the `?include=` value to send,
and a `project` that turns the document's `included` array into that model. Their `Literal`
aliases are what the tools type the parameter as.

Deliberately not a generic recursive hydrator over `included`: walking `relationships` would
faithfully reproduce Backstop's duplicate fields and leave nested pointers unresolved. The value
is in the projection layer — `backstop_client.follow_included` already covers the depth every
include here needs.
"""

from backstop_mcp.features.includes.include_plan import IncludePlan, include_plan
from backstop_mcp.features.includes.responses import (
    ActivityAttendeeResponse,
    ActivityInclude,
    ActivityIncludesResponse,
    ActivityTagChipResponse,
    CompanyRefResponse,
    ContactCardResponse,
    ContactEmailResponse,
    ContactLocationResponse,
    InternalOwnerResponse,
    OrganizationInclude,
    OrganizationIncludesResponse,
    PersonInclude,
    PersonIncludesResponse,
)
from backstop_mcp.features.includes.types import Include

__all__ = [
    "ActivityAttendeeResponse",
    "ActivityInclude",
    "ActivityIncludesResponse",
    "ActivityTagChipResponse",
    "CompanyRefResponse",
    "ContactCardResponse",
    "ContactEmailResponse",
    "ContactLocationResponse",
    "Include",
    "IncludePlan",
    "InternalOwnerResponse",
    "OrganizationInclude",
    "OrganizationIncludesResponse",
    "PersonInclude",
    "PersonIncludesResponse",
    "include_plan",
]
