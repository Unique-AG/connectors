"""The single declaration of which tools this server exposes, and what each one needs.

Each entry references the tool function object and derives its name from it, so a rename can't
silently detach a tool from its glossary. `create_app` registers from this list;
`CustomFieldGlossaryMiddleware` reads the glossary scopes from it.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from backstop_mcp.custom_fields.entity_types import KNOWN_ENTITY_TYPES
from backstop_mcp.tools.get_organization import get_organization
from backstop_mcp.tools.get_organization_custom_field import get_organization_custom_field
from backstop_mcp.tools.resolve_custom_field import resolve_custom_field
from backstop_mcp.tools.system_info import get_system_info

# Parameters stay `...` because tool signatures legitimately differ; the return type is pinned so
# a non-async function can't be registered as a tool.
type ToolFunction = Callable[..., Awaitable[object]]


@dataclass(frozen=True)
class ToolSpec:
    """One exposed MCP tool.

    `glossary_entities` are the entity types whose custom-field glossary is appended to this
    tool's description at `tools/list` time — empty for tools that don't touch custom fields.
    """

    fn: ToolFunction
    glossary_entities: tuple[str, ...] = field(default=())

    @property
    def name(self) -> str:
        """The name FastMCP registers this tool under (it defaults to the function name)."""
        return self.fn.__name__


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(get_system_info),
    ToolSpec(get_organization, glossary_entities=("organizations",)),
    ToolSpec(get_organization_custom_field, glossary_entities=("organizations",)),
    ToolSpec(resolve_custom_field, glossary_entities=KNOWN_ENTITY_TYPES),
)


def glossary_entities_by_tool_name() -> dict[str, tuple[str, ...]]:
    return {spec.name: spec.glossary_entities for spec in TOOL_SPECS if spec.glossary_entities}
