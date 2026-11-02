import json
from typing import cast

import unique_sdk

from space_config_mcp.persistence import Persistence
from space_config_mcp.upstream import Upstream


async def snapshot_space(
    *,
    upstream: Upstream,
    persistence: Persistence,
    user_id: str,
    company_id: str,
    space_id: str,
    label: str = "",
) -> dict[str, str]:
    space = await upstream.get_space(user_id, company_id, space_id)
    return persistence.save_snapshot(dict(space), label=label)


def list_snapshots(
    *,
    persistence: Persistence,
    space_id: str | None = None,
) -> list[dict[str, object]]:
    return persistence.list_snapshots(space_id=space_id)


def get_snapshot(
    *,
    persistence: Persistence,
    snapshot_id: str,
) -> dict[str, object]:
    return persistence.get_snapshot(snapshot_id)


async def revert_space(
    *,
    upstream: Upstream,
    persistence: Persistence,
    user_id: str,
    company_id: str,
    snapshot_id: str,
) -> dict[str, object]:
    snap = persistence.get_snapshot(snapshot_id)
    space_id_val = snap.get("_space_id")
    assert isinstance(space_id_val, str), f"snapshot {snapshot_id!r} missing _space_id"
    space_id = space_id_val

    pre_revert = await snapshot_space(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        label=f"pre-revert-from-{snapshot_id[:8]}",
    )

    patch: unique_sdk.Space.UpdateParams = {}
    name_val = snap.get("name")
    if isinstance(name_val, str):
        patch["name"] = name_val
    explanation_val = snap.get("explanation")
    if isinstance(explanation_val, str):
        patch["explanation"] = explanation_val
    alert_val = snap.get("alert")
    if isinstance(alert_val, str):
        patch["alert"] = alert_val
    language_model_val = snap.get("languageModel")
    if isinstance(language_model_val, str):
        patch["languageModel"] = language_model_val
    allow_model_val = snap.get("allowModelSwitching")
    if isinstance(allow_model_val, bool):
        patch["allowModelSwitching"] = allow_model_val
    is_pinned_val = snap.get("isPinned")
    if isinstance(is_pinned_val, bool):
        patch["isPinned"] = is_pinned_val

    await upstream.update_space(user_id, company_id, space_id, patch=patch)

    modules_val = snap.get("modules")
    if isinstance(modules_val, list):
        for mod_raw in cast(list[object], modules_val):
            if not isinstance(mod_raw, dict):
                continue
            mod_obj = cast(dict[str, object], mod_raw)
            mod_id = mod_obj.get("id")
            mod_config = mod_obj.get("configuration")
            if isinstance(mod_id, str) and isinstance(mod_config, dict):
                await upstream.modify_module(
                    user_id,
                    company_id,
                    mod_id,
                    configuration=cast(dict[str, object], mod_config),
                )

    return {
        "reverted_to": snapshot_id,
        "pre_revert_snapshot": pre_revert["snapshot_id"],
    }


async def export_space_config(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
) -> str:
    space = await upstream.get_space(user_id, company_id, space_id)
    return json.dumps(dict(space), default=str)


async def import_space_config(
    *,
    upstream: Upstream,
    persistence: Persistence,
    user_id: str,
    company_id: str,
    space_id: str,
    config_json: str,
) -> dict[str, object]:
    config = cast(dict[str, object], json.loads(config_json))
    pre = await snapshot_space(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        label="pre-import",
    )

    patch: unique_sdk.Space.UpdateParams = {}
    name_val = config.get("name")
    if isinstance(name_val, str):
        patch["name"] = name_val
    explanation_val = config.get("explanation")
    if isinstance(explanation_val, str):
        patch["explanation"] = explanation_val
    alert_val = config.get("alert")
    if isinstance(alert_val, str):
        patch["alert"] = alert_val
    language_model_val = config.get("languageModel")
    if isinstance(language_model_val, str):
        patch["languageModel"] = language_model_val

    await upstream.update_space(user_id, company_id, space_id, patch=patch)

    modules_val = config.get("modules")
    if isinstance(modules_val, list):
        for mod_raw in cast(list[object], modules_val):
            if not isinstance(mod_raw, dict):
                continue
            mod_obj = cast(dict[str, object], mod_raw)
            mod_id = mod_obj.get("id")
            mod_config = mod_obj.get("configuration")
            if isinstance(mod_id, str) and isinstance(mod_config, dict):
                await upstream.modify_module(
                    user_id,
                    company_id,
                    mod_id,
                    configuration=cast(dict[str, object], mod_config),
                )

    return {"imported": True, "pre_import_snapshot": pre["snapshot_id"]}
