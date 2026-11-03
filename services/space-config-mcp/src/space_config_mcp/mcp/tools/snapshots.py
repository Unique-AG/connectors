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
from space_config_mcp.mcp.dependencies import get_space_id
from space_config_mcp.mcp.dependencies import get_upstream
from space_config_mcp.persistence import Persistence
from space_config_mcp.shared import SpaceConfigError
from space_config_mcp.upstream import Upstream

_META = merge_tool_meta(
    {},
    ContextRequirements(required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID, MetaKeys.ASSISTANT_ID]),
)


@tool(
    title="Snapshot Space",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def snapshot_space(
    *,
    label: Annotated[
        str,
        Field(description="Human-readable label for this snapshot. Auto-generated if empty."),
    ] = "",
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> dict[str, str]:
    """Capture the full configuration of the current space as a versioned JSON snapshot.

    Stores the snapshot in the knowledge base. Returns snapshot_id for later revert.
    Each call creates a new version of the space's snapshot file.
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
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> list[dict[str, object]]:
    """List all stored snapshots for the current space, newest version first.

    Returns snapshot_id (a KB contentVersionId), version_number, label, and captured_at
    for each snapshot. Pass snapshot_id to get_snapshot or revert_space.
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
    snapshot_id: Annotated[str, Field(description="Snapshot ID returned by list_snapshots.")],
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> dict[str, object]:
    """Return the full JSON config stored in a specific snapshot version.

    Reflects the space config at the time snapshot_space was called for that version.
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
    snapshot_id: Annotated[str, Field(description="Snapshot ID returned by list_snapshots.")],
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> dict[str, object]:
    """Restore the current space to a prior snapshot version.

    Auto-snapshots the current state first so the revert itself is reversible.
    Returns the pre-revert snapshot ID alongside the restored snapshot ID.
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
    title="Delete Snapshots",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def delete_snapshots(
    *,
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> dict[str, object]:
    """Delete all stored snapshots for the current space.

    Removes the snapshot file and every version it contains. This cannot be undone.
    Individual version deletion is not supported by the KB API.
    """
    user_id, company_id = caller
    return await contexts.delete_snapshots(
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
    )


@tool(
    title="Export Space Config",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def export_space_config(
    *,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> str:
    """Return the current space config as a portable JSON string. No storage side-effects.

    Reflects live config at call time. Use snapshot_space to persist a named version.
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
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> dict[str, object]:
    """Apply a previously exported JSON config to the current space. Auto-snapshots before applying."""
    user_id, company_id = caller
    return await contexts.import_space_config(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        config_json=config_json,
    )
