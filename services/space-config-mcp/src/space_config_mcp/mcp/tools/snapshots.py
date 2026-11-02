from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from space_config_mcp import contexts
from space_config_mcp.mcp.dependencies import get_persistence
from space_config_mcp.mcp.dependencies import get_upstream
from space_config_mcp.persistence import Persistence
from space_config_mcp.shared import SpaceConfigError
from space_config_mcp.upstream import Upstream


@tool(
    title="Snapshot Space",
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def snapshot_space(
    *,
    user_id: Annotated[str, Field(description="Unique platform user ID of the caller.")],
    company_id: Annotated[str, Field(description="Unique platform company ID of the caller.")],
    space_id: Annotated[str, Field(description="ID of the space to snapshot.")],
    label: Annotated[
        str,
        Field(description="Human-readable label for this snapshot. Auto-generated if empty."),
    ] = "",
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> dict[str, str]:
    """Capture the full space configuration as a named JSON snapshot. Returns snapshot_id."""
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
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def list_snapshots(
    *,
    space_id: Annotated[
        str | None,
        Field(description="Filter snapshots to this space ID. Omit to list all."),
    ] = None,
    persistence: Persistence = Depends(get_persistence),
) -> list[dict[str, object]]:
    """List stored snapshots, sorted newest first. Optionally filter by space_id."""
    return contexts.list_snapshots(persistence=persistence, space_id=space_id)


@tool(
    title="Get Snapshot",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def get_snapshot(
    *,
    snapshot_id: Annotated[str, Field(description="ID of the snapshot to retrieve.")],
    persistence: Persistence = Depends(get_persistence),
) -> dict[str, object]:
    """Return the full JSON content of a stored snapshot."""
    try:
        return contexts.get_snapshot(persistence=persistence, snapshot_id=snapshot_id)
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    title="Revert Space",
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def revert_space(
    *,
    user_id: Annotated[str, Field(description="Unique platform user ID of the caller.")],
    company_id: Annotated[str, Field(description="Unique platform company ID of the caller.")],
    snapshot_id: Annotated[str, Field(description="ID of the snapshot to restore from.")],
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> dict[str, object]:
    """Restore a space to a prior snapshot. Auto-snapshots current state first."""
    try:
        return await contexts.revert_space(
            upstream=upstream,
            persistence=persistence,
            user_id=user_id,
            company_id=company_id,
            snapshot_id=snapshot_id,
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    title="Export Space Config",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def export_space_config(
    *,
    user_id: Annotated[str, Field(description="Unique platform user ID of the caller.")],
    company_id: Annotated[str, Field(description="Unique platform company ID of the caller.")],
    space_id: Annotated[str, Field(description="ID of the space to export.")],
    upstream: Upstream = Depends(get_upstream),
) -> str:
    """Return a portable JSON string of the full space config. No storage side-effects."""
    return await contexts.export_space_config(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
    )


@tool(
    title="Import Space Config",
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def import_space_config(
    *,
    user_id: Annotated[str, Field(description="Unique platform user ID of the caller.")],
    company_id: Annotated[str, Field(description="Unique platform company ID of the caller.")],
    space_id: Annotated[str, Field(description="ID of the space to apply the config to.")],
    config_json: Annotated[
        str,
        Field(
            description=(
                "JSON string previously returned by export_space_config. "
                "Auto-snapshots current state before applying."
            )
        ),
    ],
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> dict[str, object]:
    """Apply a previously exported JSON config to a space. Auto-snapshots before applying."""
    return await contexts.import_space_config(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        config_json=config_json,
    )
