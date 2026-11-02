import unique_sdk

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
    module_id: str,
) -> unique_sdk.Module:
    return await upstream.get_module(user_id, company_id, module_id)
