from typing import cast

import unique_sdk

from space_config_mcp.shared import ClaudeSDKConfig
from space_config_mcp.shared import CodexSDKConfig
from space_config_mcp.shared import ConductConfig
from space_config_mcp.shared import ConductSetupConfig
from space_config_mcp.shared import ConductStrategy
from space_config_mcp.shared import PiAgentSDKConfig
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
    """Return the SwappableIntelligence module ID and its parsed ConductConfig."""
    modules = await upstream.list_modules(user_id, company_id, space_id)
    mod = next((m for m in modules if m.name == _CONDUCT_MODULE_NAME), None)
    if mod is None:
        raise SpaceConfigError(f"No {_CONDUCT_MODULE_NAME} module found on space {space_id!r}")
    raw: dict[str, object] = cast(dict[str, object], mod.configuration or {})
    config = ConductConfig.model_validate(raw)
    return {"module_id": mod.id, "configuration": config.model_dump(by_alias=True)}


def _deep_merge(base: dict[str, object], patch: dict[str, object]) -> dict[str, object]:
    """Return a new dict with patch merged into base. Nested dicts are merged recursively."""
    result = dict(base)
    for key, value in patch.items():
        base_value = result.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            result[key] = _deep_merge(
                cast(dict[str, object], base_value),
                cast(dict[str, object], value),
            )
        else:
            result[key] = value
    return result


async def update_conduct_config(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
    strategy: ConductStrategy | None = None,
    max_turns: int | None = None,
    claude_patch: ClaudeSDKConfig | None = None,
    pi_agent_patch: PiAgentSDKConfig | None = None,
    codex_patch: CodexSDKConfig | None = None,
    setup_patch: ConductSetupConfig | None = None,
) -> unique_sdk.Module:
    """Merge typed patches into the Conduct harness configuration."""
    modules = await upstream.list_modules(user_id, company_id, space_id)
    mod = next((m for m in modules if m.name == _CONDUCT_MODULE_NAME), None)
    if mod is None:
        raise SpaceConfigError(f"No {_CONDUCT_MODULE_NAME} module found on space {space_id!r}")

    config: dict[str, object] = cast(dict[str, object], mod.configuration or {}).copy()

    if strategy is not None:
        config["strategy"] = strategy

    if max_turns is not None:
        active = config.get("strategy") or "claude_code"
        if active in ("claude_code", "claude_sandbox"):
            key = "claude"
        elif active == "pi_agent":
            key = "piAgent"
        else:
            key = str(active)
        block = cast(dict[str, object], config.get(key) or {})
        config[key] = {**block, "maxTurns": max_turns}

    if claude_patch is not None:
        patch_dict = claude_patch.model_dump(by_alias=True, exclude_none=True)
        existing = cast(dict[str, object], config.get("claude") or {})
        config["claude"] = _deep_merge(existing, patch_dict)

    if pi_agent_patch is not None:
        patch_dict = pi_agent_patch.model_dump(by_alias=True, exclude_none=True)
        existing = cast(dict[str, object], config.get("piAgent") or {})
        config["piAgent"] = _deep_merge(existing, patch_dict)

    if codex_patch is not None:
        patch_dict = codex_patch.model_dump(by_alias=True, exclude_none=True)
        existing = cast(dict[str, object], config.get("codex") or {})
        config["codex"] = _deep_merge(existing, patch_dict)

    if setup_patch is not None:
        patch_dict = setup_patch.model_dump(by_alias=True, exclude_none=True)
        existing = cast(dict[str, object], config.get("setup") or {})
        config["setup"] = _deep_merge(existing, patch_dict)

    return await upstream.modify_module(user_id, company_id, mod.id, configuration=config)
