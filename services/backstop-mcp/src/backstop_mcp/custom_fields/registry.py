from __future__ import annotations

# Maps MCP tool function names → entity types whose custom-field glossary should
# be appended to that tool's description at tools/list time.
TOOL_ENTITY_GLOSSARY: dict[str, tuple[str, ...]] = {
    "get_organization": ("organizations",),
    "get_organization_custom_field": ("organizations",),
    "resolve_custom_field": (
        "organizations",
        "contacts",
        "people",
        "employees",
        "opportunities",
        "accounts",
    ),
}
