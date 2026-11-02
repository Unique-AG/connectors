from typing import cast

import unique_sdk

from space_config_mcp.shared import SpaceConfigError
from space_config_mcp.upstream import Upstream

_CONDUCT_MODULE_NAME = "SwappableIntelligence"


async def update_module_config(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    module_id: str,
    config_patch: dict[str, object],
) -> unique_sdk.Module:
    """Merge config_patch into a module's configuration dict, preserving unpatched keys."""
    current = await upstream.get_module(user_id, company_id, module_id)
    existing_config: dict[str, object] = cast(dict[str, object], current.configuration or {})
    merged = {**existing_config, **config_patch}
    return await upstream.modify_module(user_id, company_id, module_id, configuration=merged)


async def get_conduct_config(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
) -> dict[str, object]:
    modules = await upstream.list_modules(user_id, company_id, space_id)
    mod = next((m for m in modules if m.name == _CONDUCT_MODULE_NAME), None)
    if mod is None:
        raise SpaceConfigError(f"No {_CONDUCT_MODULE_NAME} module found on space {space_id!r}")
    return {"module_id": mod.id, "configuration": cast(dict[str, object], mod.configuration or {})}


async def update_conduct_config(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
    max_turns: int | None = None,
    setup_patch: dict[str, object] | None = None,
) -> unique_sdk.Module:
    modules = await upstream.list_modules(user_id, company_id, space_id)
    mod = next((m for m in modules if m.name == _CONDUCT_MODULE_NAME), None)
    if mod is None:
        raise SpaceConfigError(f"No {_CONDUCT_MODULE_NAME} module found on space {space_id!r}")
    config: dict[str, object] = cast(dict[str, object], mod.configuration or {}).copy()
    if max_turns is not None:
        claude_raw = config.get("claude")
        claude_block: dict[str, object] = (
            cast(dict[str, object], claude_raw).copy() if isinstance(claude_raw, dict) else {}
        )
        claude_block["maxTurns"] = max_turns
        config["claude"] = claude_block
    if setup_patch is not None:
        setup_raw = config.get("setup")
        setup_block: dict[str, object] = (
            cast(dict[str, object], setup_raw).copy() if isinstance(setup_raw, dict) else {}
        )
        setup_block.update(setup_patch)
        config["setup"] = setup_block
    return await upstream.modify_module(user_id, company_id, mod.id, configuration=config)
