from typing import TypedDict

from mcp_types import ToolAnnotations

FREE_READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
PAID_READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
PAID_ORDER = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)


class ToolOptions(TypedDict):
    title: str
    annotations: ToolAnnotations
    meta: dict[str, str]


def tool_options(
    title: str, annotations: ToolAnnotations, *, icon: str, system_prompt: str
) -> ToolOptions:
    """The `@tool` arguments the Unique platform reads: title, hints, icon and system prompt."""
    return {
        "title": title,
        "annotations": annotations.model_copy(update={"title": title}),
        "meta": {"unique.app/icon": icon, "unique.app/system-prompt": system_prompt},
    }
