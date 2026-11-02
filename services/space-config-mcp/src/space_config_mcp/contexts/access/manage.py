from typing import cast

import unique_sdk

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
    user_id: str,
    company_id: str,
    space_id: str,
    access: list[dict[str, object]],
) -> unique_sdk.Space.SpaceAccessResponse:
    typed_access = cast(list[unique_sdk.Space.AccessEntry], access)
    return await upstream.add_space_access(user_id, company_id, space_id, access=typed_access)


async def delete_space_access(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
    access_ids: list[str],
) -> unique_sdk.Space.DeleteSpaceAccessResponse:
    return await upstream.delete_space_access(user_id, company_id, space_id, access_ids=access_ids)
