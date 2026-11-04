from typing import Literal
from typing import cast

import unique_sdk

from space_config_mcp.contexts.snapshots import snapshot_space
from space_config_mcp.persistence import Persistence
from space_config_mcp.shared import AssistantPrompt
from space_config_mcp.shared import McpServerParam
from space_config_mcp.shared import SwitchableLanguageModel
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
    switchable_language_models: list[SwitchableLanguageModel] | None = None,
    is_pinned: bool | None = None,
    chat_upload: Literal["ENABLED", "DISABLED"] | None = None,
    settings: dict[str, object] | None = None,
    assistant_prompts: list[AssistantPrompt] | None = None,
    mcp_servers: list[McpServerParam] | None = None,
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
    if switchable_language_models is not None:
        patch["switchableLanguageModels"] = cast(
            list[unique_sdk.Space.SwitchableLanguageModel],
            [m.model_dump(by_alias=True) for m in switchable_language_models],
        )
    if is_pinned is not None:
        patch["isPinned"] = is_pinned
    if chat_upload is not None:
        patch["chatUpload"] = chat_upload
    if settings is not None:
        patch["settings"] = settings
    if assistant_prompts is not None:
        patch["assistantPrompts"] = cast(
            list[unique_sdk.Space.AssistantPromptParams],
            [p.model_dump(exclude_none=True) for p in assistant_prompts],
        )
    if mcp_servers is not None:
        patch["mcpServers"] = cast(
            list[unique_sdk.Space.McpServerParams],
            [s.model_dump(by_alias=True, exclude_none=True) for s in mcp_servers],
        )
    return await upstream.update_space(user_id, company_id, space_id, patch=patch)
