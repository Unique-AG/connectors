from typing import cast

import unique_sdk

from space_config_mcp.contexts.snapshots import snapshot_space
from space_config_mcp.persistence import Persistence
from space_config_mcp.upstream import Upstream


async def get_space_access(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
) -> unique_sdk.Space.SpaceAccessResponse:
    return await upstream.get_space_access(user_id, company_id, space_id)


async def add_space_access(
    *,
    upstream: Upstream,
    persistence: Persistence,
    user_id: str,
    company_id: str,
    space_id: str,
    access: list[dict[str, object]],
) -> unique_sdk.Space.SpaceAccessResponse:
    await snapshot_space(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        label="pre-add_space_access",
    )
    typed_access = cast(list[unique_sdk.Space.AccessEntry], access)
    return await upstream.add_space_access(user_id, company_id, space_id, access=typed_access)


async def delete_space_access(
    *,
    upstream: Upstream,
    persistence: Persistence,
    user_id: str,
    company_id: str,
    space_id: str,
    access_ids: list[str],
) -> unique_sdk.Space.DeleteSpaceAccessResponse:
    await snapshot_space(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        label="pre-delete_space_access",
    )
    return await upstream.delete_space_access(user_id, company_id, space_id, access_ids=access_ids)
