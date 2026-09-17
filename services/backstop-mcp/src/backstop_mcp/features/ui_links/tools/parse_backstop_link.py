from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.ui_links import (
    ParseEntityLinkResult,
    ParseEntityLinkUtil,
)
from backstop_mcp.features.ui_links.dependencies import (
    get_effective_ui_base_url,
    get_parse_entity_link_util_factory,
)
from backstop_mcp.models import published_output_schema


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(ParseEntityLinkResult),
)
async def parse_backstop_link(
    url: Annotated[
        str,
        Field(
            description=(
                "A pasted Backstop CRM UI URL. On success, call `suggested_tool` with the "
                "echoed `entity_id` when one is present. Read `suggested_note` first — an "
                "account id is not a party id."
            ),
        ),
    ],
    parse_entity_link_util: ParseEntityLinkUtil = Depends(get_parse_entity_link_util_factory),
    ui_base_url: str | None = Depends(get_effective_ui_base_url),
) -> ParseEntityLinkResult:
    """Parse a pasted Backstop CRM UI URL into page, id, tab, and layout.

    Paste a CRM URL, then call `suggested_tool` with the echoed `entity_id` when one is
    present. Read `suggested_note` before calling a party-scoped tool — an account id is not
    a party id, and a task URL does not load via `get_tasks_for_party`. Unrecognized URLs
    return `status=unrecognized`; do not invent a target. A configured UI host that differs
    from the pasted host sets `host_mismatch=true` but the URL is still parsed.

    Call like: {"url": "https://tenant.example.test/backstop/crm/ManageOrganization.action?party_id=<id>"}
    """
    return parse_entity_link_util.run(url=url, ui_base_url=ui_base_url)
