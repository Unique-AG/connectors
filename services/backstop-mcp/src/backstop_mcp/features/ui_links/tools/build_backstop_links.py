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
from backstop_mcp.features.ui_links.dependencies import (
    get_build_entity_link_util_factory,
    get_effective_ui_base_url,
)
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
                "Discriminated target: `kind` plus that kind's id (`party_id`, `entity_id`, "
                "`task_id`, or `entity_activity_details_id`). Echo ids from prior tools; never "
                "invent one. An account id is not a party id. Email uses "
                "`entity_activity_details_id` from search_activities / get_activity_detail, "
                "never a get_activity_history email `activity_id`."
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
                "Optional layout name from list_custom_fields (`layout_name`). Adds a layout "
                "URL only when `view_entity_type` is also set. Never invent or hardcode a "
                "layout name."
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
    ui_base_url: str | None = Depends(get_effective_ui_base_url),
) -> BuildEntityLinkResult:
    """Build labeled Backstop CRM UI URLs for one already-resolved record.

    `target` is a discriminated union (`kind` plus that kind's id). Echo ids from prior tools;
    never invent one. An account id is not a party id. Email uses `entity_activity_details_id`
    from `search_activities` or `get_activity_detail` — never a `get_activity_history` email
    `activity_id`.

    Omit `tabs` to receive every allowed tab for the page plus the canonical no-tab URL
    (product summary is omission, never `viewType=summary`). Pass `tabs=[]` for the canonical
    URL only. Pass both `layout_name` and `view_entity_type` from `list_custom_fields` to add
    a layout link; never fetch or invent those names.

    When this deployment has no UI origin the status is `not_configured` — do not invent a host.

    Call like: {"target": {"kind": "organization", "party_id": "<id from prior resolve echo>"}}
    """
    return build_entity_link_util.run(
        target=target,
        ui_base_url=ui_base_url,
        tabs=tabs,
        layout_name=layout_name,
        view_entity_type=view_entity_type,
    )
