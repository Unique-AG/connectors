from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field
from unique_mcp.meta.context_requirements import ContextRequirements
from unique_mcp.meta.keys import MetaKeys
from unique_mcp.meta.part import merge_tool_meta

from space_config_mcp import contexts
from space_config_mcp.mcp.dependencies import get_caller
from space_config_mcp.mcp.dependencies import get_persistence
from space_config_mcp.mcp.dependencies import get_upstream
from space_config_mcp.persistence import Persistence
from space_config_mcp.shared import SpaceConfigError
from space_config_mcp.upstream import Upstream

_META = merge_tool_meta({}, ContextRequirements(required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID]))


@tool(
    title="Snapshot Space",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def snapshot_space(
    *,
    space_id: Annotated[str, Field(description="ID of the space to snapshot.")],
    label: Annotated[
        str,
        Field(description="Human-readable label for this snapshot. Auto-generated if empty."),
    ] = "",
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
) -> dict[str, str]:
    """Capture the full space configuration as a named JSON snapshot stored in the knowledge base.

    Returns snapshot_id for later revert. Snapshots are point-in-time captures:
    config changes made through the portal since the last snapshot are not reflected.
    """
    user_id, company_id = caller
    return await contexts.snapshot_space(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        label=label,
    )


@tool(
    title="List Snapshots",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def list_snapshots(
    *,
    space_id: Annotated[str, Field(description="ID of the space to list snapshots for.")],
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
) -> list[dict[str, object]]:
    """List snapshots for a space stored in the knowledge base, newest first.

    Only shows snapshots created by this MCP. Config changes made in the
    portal since the last snapshot are not reflected.
    """
    user_id, company_id = caller
    return await contexts.list_snapshots(
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
    )


@tool(
    title="Get Snapshot",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_snapshot(
    *,
    space_id: Annotated[str, Field(description="ID of the space the snapshot belongs to.")],
    snapshot_id: Annotated[str, Field(description="ID of the snapshot to retrieve.")],
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
) -> dict[str, object]:
    """Return the full JSON content of a stored snapshot.

    Snapshots reflect the space config at the time snapshot_space was called.
    Changes made through the portal since then are not included.
    """
    user_id, company_id = caller
    try:
        return await contexts.get_snapshot(
            persistence=persistence,
            user_id=user_id,
            company_id=company_id,
            space_id=space_id,
            snapshot_id=snapshot_id,
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    title="Revert Space",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def revert_space(
    *,
    space_id: Annotated[str, Field(description="ID of the space to revert.")],
    snapshot_id: Annotated[str, Field(description="ID of the snapshot to restore from.")],
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
) -> dict[str, object]:
    """Restore a space to a prior snapshot. Auto-snapshots current state first.

    Snapshots reflect the config at the time snapshot_space was called.
    Portal changes made since then are not part of the snapshot and will be lost on revert.
    """
    user_id, company_id = caller
    try:
        return await contexts.revert_space(
            upstream=upstream,
            persistence=persistence,
            user_id=user_id,
            company_id=company_id,
            snapshot_id=snapshot_id,
            space_id=space_id,
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    title="Export Space Config",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def export_space_config(
    *,
    space_id: Annotated[str, Field(description="ID of the space to export.")],
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
) -> str:
    """Return a portable JSON string of the full space config. No storage side-effects.

    Reflects the live config at call time. Use snapshot_space to persist a named version.
    """
    user_id, company_id = caller
    return await contexts.export_space_config(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
    )


@tool(
    title="Import Space Config",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def import_space_config(
    *,
    space_id: Annotated[str, Field(description="ID of the space to apply the config to.")],
    config_json: Annotated[
        str,
        Field(
            description=(
                "JSON string previously returned by export_space_config. "
                "Auto-snapshots current state before applying. "
                "Portal changes since the export was taken are not included."
            )
        ),
    ],
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
) -> dict[str, object]:
    """Apply a previously exported JSON config to a space. Auto-snapshots before applying."""
    user_id, company_id = caller
    return await contexts.import_space_config(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        config_json=config_json,
    )
