import unique_sdk

from space_config_mcp.shared import SpaceConfigError
from space_config_mcp.upstream import Upstream


async def list_modules(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
) -> list[unique_sdk.Module]:
    return await upstream.list_modules(user_id, company_id, space_id)


async def get_module(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
    module_id: str,
) -> unique_sdk.Module:
    modules = await upstream.list_modules(user_id, company_id, space_id)
    mod = next((m for m in modules if m.id == module_id), None)
    if mod is None:
        raise SpaceConfigError(f"Module {module_id!r} not found in space {space_id!r}")
    return mod
