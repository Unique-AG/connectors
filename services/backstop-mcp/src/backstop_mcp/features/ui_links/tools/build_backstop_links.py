from collections.abc import Sequence
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.ui_links import (
    BackstopLinkTarget,
    BuildEntityLinkResult,
    BuildEntityLinkUtil,
)
from backstop_mcp.features.ui_links.dependencies import get_build_entity_link_util_factory
from backstop_mcp.models import published_output_schema


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(BuildEntityLinkResult),
)
async def build_backstop_links(
    target: Annotated[
        BackstopLinkTarget,
        Field(
            description=(
                "Discriminated target: `kind` plus that kind's id. Activity kinds take the "
                "bare `id` of a `search_activities` row — never a `meeting-or-calls_…` "
                "handle. Rows already carry `url` when that field is selected. An account "
                "id is not a party id."
            ),
        ),
    ],
    tabs: Annotated[
        Sequence[str] | None,
        Field(
            description=(
                "Optional tab names for this page. Omit (null) to return every allowed tab "
                "plus the canonical no-tab URL. Pass an empty list for the canonical URL "
                "only. Product summary is omission — never request `viewType=summary`."
            ),
        ),
    ] = None,
    layout_name: Annotated[
        str | None,
        Field(
            description=(
                "Optional layout name from list_custom_fields (`layout_name`). A layout URL "
                "is built for organization, person, account, product, and opportunity only, "
                "and only when `view_entity_type` is also set. Email, task, and activity "
                "drop it. Never invent or hardcode a layout name."
            ),
        ),
    ] = None,
    view_entity_type: Annotated[
        str | None,
        Field(
            description=(
                "Optional Bean type from list_custom_fields (`entity_type`). Adds a layout "
                "URL only when `layout_name` is also set."
            ),
        ),
    ] = None,
    build_entity_link_util: BuildEntityLinkUtil = Depends(get_build_entity_link_util_factory),
) -> BuildEntityLinkResult:
    """Build labeled Backstop CRM UI URLs for one already-resolved record.

    `target` is a discriminated union (`kind` plus that kind's id). Echo ids from prior tools;
    never invent one. An account id is not a party id. Activity links take the bare `id` of
    a `search_activities` row. Never a `meeting-or-calls_…` handle.

    Omit `tabs` to receive every allowed tab for the page plus the canonical no-tab URL.
    Product summary is the no-tab URL; do not request `summary`. Pass `tabs=[]` for the
    canonical URL only. A layout URL is organization, person, account, product, and
    opportunity only — also dropped for email, task, and activity. Pass both `layout_name`
    and `view_entity_type` from `list_custom_fields` for those five; never invent them.

    When this deployment has no UI origin the status is `not_configured` — do not invent a host.

    Call like: {"target": {"kind": "organization", "party_id": "<id from prior resolve echo>"}}
    """
    return build_entity_link_util.run(
        target=target,
        tabs=tabs,
        layout_name=layout_name,
        view_entity_type=view_entity_type,
    )
