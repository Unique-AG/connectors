import unique_sdk

from space_config_mcp.contexts.snapshots import snapshot_space
from space_config_mcp.persistence import Persistence
from space_config_mcp.upstream import Upstream


async def update_space(
    *,
    upstream: Upstream,
    persistence: Persistence,
    user_id: str,
    company_id: str,
    space_id: str,
    name: str | None = None,
    explanation: str | None = None,
    alert: str | None = None,
    language_model: str | None = None,
    allow_model_switching: bool | None = None,
    is_pinned: bool | None = None,
    settings: dict[str, object] | None = None,
) -> unique_sdk.Space:
    await snapshot_space(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        label="pre-update_space",
    )
    patch: unique_sdk.Space.UpdateParams = {}
    if name is not None:
        patch["name"] = name
    if explanation is not None:
        patch["explanation"] = explanation
    if alert is not None:
        patch["alert"] = alert
    if language_model is not None:
        patch["languageModel"] = language_model
    if allow_model_switching is not None:
        patch["allowModelSwitching"] = allow_model_switching
    if is_pinned is not None:
        patch["isPinned"] = is_pinned
    if settings is not None:
        patch["settings"] = settings
    return await upstream.update_space(user_id, company_id, space_id, patch=patch)
