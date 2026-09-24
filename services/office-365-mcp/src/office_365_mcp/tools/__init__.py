from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx
from fastmcp import FastMCP

from office_365_mcp.shared.seam import ToolAdvice, graph_scope
from office_365_mcp.tools import (
    get_me,
    onenote_append_to_page,
    onenote_copy_notebook,
    onenote_copy_page,
    onenote_copy_section,
    onenote_create_notebook,
    onenote_create_page,
    onenote_create_section,
    onenote_create_section_group,
    onenote_delete_page,
    onenote_edit_page,
    onenote_find_notebook_from_url,
    onenote_get_operation,
    onenote_list_notebooks,
    onenote_list_pages,
    onenote_list_recent_notebooks,
    onenote_list_sections,
    onenote_preview_page,
    onenote_read_page,
    onenote_read_resource,
    onenote_rename_page,
    outlook_browse_folders,
    outlook_cancel_event,
    outlook_check_availability,
    outlook_create_event,
    outlook_create_event_on_behalf,
    outlook_disable_mail_rule,
    outlook_draft_mail,
    outlook_draft_reply,
    outlook_find_recipient,
    outlook_get_mailbox_settings,
    outlook_list_calendars,
    outlook_list_categories,
    outlook_list_events,
    outlook_list_mail,
    outlook_mark_mail,
    outlook_move_mail,
    outlook_read_event,
    outlook_read_mail,
    outlook_read_thread,
    outlook_respond_to_invite,
    outlook_search_mail,
    outlook_send_draft,
    outlook_set_automatic_reply,
    outlook_suggest_meeting_times,
    outlook_update_event,
    sharepoint_browse_folder,
    sharepoint_read_file,
    sharepoint_search_files,
    teams_browse_channel,
    teams_list_channels,
    teams_list_chats,
    teams_list_meeting_recordings,
    teams_list_meeting_transcripts,
    teams_list_my_teams,
    teams_read_message,
    teams_read_transcript,
    teams_search_messages,
)

__all__ = [
    "ALWAYS_ON",
    "PRESETS",
    "TOOL_NAMES",
    "GraphCallExample",
    "Selection",
    "graph_advice",
    "graph_call_examples",
    "register_tools",
    "resolve",
]


class ToolModule(Protocol):
    @property
    def TOOL_NAME(self) -> str: ...

    GRAPH_PERMISSIONS: tuple[str, ...]

    @property
    def GRAPH_CALL_EXAMPLE(self) -> Mapping[str, object]: ...

    @staticmethod
    def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None: ...


@runtime_checkable
class _NarrowsItsNotFound(Protocol):
    @property
    def GRAPH_NOT_FOUND(self) -> str: ...


@runtime_checkable
class _NarrowsItsCall(Protocol):
    @property
    def GRAPH_CALL_NARROWS_TO(self) -> tuple[str, ...]: ...


_TOOL_MODULES: tuple[ToolModule, ...] = (
    get_me,
    teams_list_chats,
    teams_list_my_teams,
    teams_list_channels,
    teams_browse_channel,
    teams_search_messages,
    teams_read_message,
    teams_list_meeting_transcripts,
    teams_read_transcript,
    teams_list_meeting_recordings,
    outlook_search_mail,
    outlook_read_mail,
    outlook_browse_folders,
    outlook_find_recipient,
    outlook_read_thread,
    outlook_list_mail,
    outlook_get_mailbox_settings,
    outlook_mark_mail,
    outlook_move_mail,
    outlook_draft_mail,
    outlook_draft_reply,
    outlook_send_draft,
    outlook_set_automatic_reply,
    outlook_disable_mail_rule,
    outlook_list_categories,
    outlook_list_calendars,
    outlook_list_events,
    outlook_read_event,
    outlook_check_availability,
    outlook_suggest_meeting_times,
    outlook_create_event,
    outlook_create_event_on_behalf,
    outlook_update_event,
    outlook_cancel_event,
    outlook_respond_to_invite,
    sharepoint_search_files,
    sharepoint_browse_folder,
    sharepoint_read_file,
    onenote_list_notebooks,
    onenote_list_pages,
    onenote_read_page,
    onenote_create_page,
    onenote_append_to_page,
    onenote_preview_page,
    onenote_read_resource,
    onenote_find_notebook_from_url,
    onenote_list_recent_notebooks,
    onenote_list_sections,
    onenote_create_notebook,
    onenote_create_section,
    onenote_create_section_group,
    onenote_edit_page,
    onenote_rename_page,
    onenote_copy_page,
    onenote_copy_section,
    onenote_copy_notebook,
    onenote_get_operation,
    onenote_delete_page,
)

TOOL_NAMES: tuple[str, ...] = tuple(module.TOOL_NAME for module in _TOOL_MODULES)

ALWAYS_ON: str = get_me.TOOL_NAME

PRESETS: Mapping[str, tuple[str, ...]] = {
    "teams": (
        "teams_list_chats",
        "teams_list_my_teams",
        "teams_list_channels",
        "teams_browse_channel",
        "teams_search_messages",
        "teams_read_message",
        "teams_list_meeting_transcripts",
        "teams_read_transcript",
        "teams_list_meeting_recordings",
    ),
    "teams-chat": ("teams_list_chats",),
    "teams-messages": ("teams_list_chats", "teams_search_messages", "teams_read_message"),
    "teams-channels": ("teams_list_my_teams", "teams_list_channels", "teams_browse_channel"),
    "teams-transcripts": (
        "teams_list_chats",
        "teams_list_meeting_transcripts",
        "teams_read_transcript",
    ),
    "teams-recordings": ("teams_list_chats", "teams_list_meeting_recordings"),
    "teams-meetings": (
        "teams_list_chats",
        "teams_list_meeting_transcripts",
        "teams_read_transcript",
        "teams_list_meeting_recordings",
    ),
    "outlook-read": (
        "outlook_search_mail",
        "outlook_read_mail",
        "outlook_browse_folders",
        "outlook_find_recipient",
        "outlook_read_thread",
        "outlook_list_mail",
    ),
    "outlook-write": (
        "outlook_search_mail",
        "outlook_read_mail",
        "outlook_browse_folders",
        "outlook_find_recipient",
        "outlook_read_thread",
        "outlook_list_mail",
        "outlook_mark_mail",
        "outlook_move_mail",
        "outlook_draft_mail",
        "outlook_draft_reply",
    ),
    "outlook-send": (
        "outlook_search_mail",
        "outlook_read_mail",
        "outlook_browse_folders",
        "outlook_find_recipient",
        "outlook_read_thread",
        "outlook_list_mail",
        "outlook_mark_mail",
        "outlook_move_mail",
        "outlook_draft_mail",
        "outlook_draft_reply",
        "outlook_send_draft",
    ),
    "outlook-mailbox": ("outlook_get_mailbox_settings", "outlook_list_categories"),
    "outlook-automate": (
        "outlook_get_mailbox_settings",
        "outlook_set_automatic_reply",
        "outlook_disable_mail_rule",
    ),
    "outlook-calendar": (
        "outlook_list_calendars",
        "outlook_list_events",
        "outlook_read_event",
        "outlook_check_availability",
        "outlook_suggest_meeting_times",
    ),
    "outlook-calendar-write": (
        "outlook_list_calendars",
        "outlook_list_events",
        "outlook_read_event",
        "outlook_check_availability",
        "outlook_suggest_meeting_times",
        "outlook_create_event",
        "outlook_update_event",
        "outlook_cancel_event",
        "outlook_respond_to_invite",
    ),
    "outlook-calendar-delegate": (
        "outlook_list_calendars",
        "outlook_list_events",
        "outlook_read_event",
        "outlook_check_availability",
        "outlook_suggest_meeting_times",
        "outlook_create_event",
        "outlook_update_event",
        "outlook_cancel_event",
        "outlook_respond_to_invite",
        "outlook_create_event_on_behalf",
    ),
    "sharepoint-search": ("sharepoint_search_files", "sharepoint_browse_folder"),
    "sharepoint-read": (
        "sharepoint_search_files",
        "sharepoint_browse_folder",
        "sharepoint_read_file",
    ),
    "onenote-read": (
        "onenote_list_notebooks",
        "onenote_list_pages",
        "onenote_read_page",
        "onenote_preview_page",
        "onenote_read_resource",
        "onenote_find_notebook_from_url",
        "onenote_list_recent_notebooks",
        "onenote_list_sections",
    ),
    "onenote-write": (
        "onenote_list_notebooks",
        "onenote_list_pages",
        "onenote_read_page",
        "onenote_preview_page",
        "onenote_read_resource",
        "onenote_find_notebook_from_url",
        "onenote_list_recent_notebooks",
        "onenote_list_sections",
        "onenote_create_page",
        "onenote_append_to_page",
        "onenote_create_notebook",
        "onenote_create_section",
        "onenote_create_section_group",
        "onenote_edit_page",
        "onenote_rename_page",
        "onenote_copy_page",
        "onenote_copy_section",
        "onenote_copy_notebook",
        "onenote_get_operation",
    ),
    "onenote-delete": (
        "onenote_list_notebooks",
        "onenote_list_pages",
        "onenote_read_page",
        "onenote_preview_page",
        "onenote_read_resource",
        "onenote_find_notebook_from_url",
        "onenote_list_recent_notebooks",
        "onenote_list_sections",
        "onenote_create_page",
        "onenote_append_to_page",
        "onenote_create_notebook",
        "onenote_create_section",
        "onenote_create_section_group",
        "onenote_edit_page",
        "onenote_rename_page",
        "onenote_copy_page",
        "onenote_copy_section",
        "onenote_copy_notebook",
        "onenote_get_operation",
        "onenote_delete_page",
    ),
}


@dataclass(frozen=True, slots=True)
class Selection:
    preset: str | None
    tools: tuple[str, ...]
    permissions: tuple[str, ...]
    graph_scopes: tuple[str, ...]


def resolve(*, preset: str | None, enabled: Sequence[str] | None) -> Selection:
    assert (preset is None) != (enabled is None), (
        "exactly one of preset and enabled is a selection, which SurfaceConfig guarantees "
        + f"(got preset={preset!r}, enabled={enabled!r})"
    )
    if preset is not None:
        assert preset in PRESETS, (
            f"no tools are mapped for preset {preset!r} — config.ToolsPreset and PRESETS have "
            + f"drifted apart (mapped: {sorted(PRESETS)})"
        )
        asked_for = PRESETS[preset]
        assert not _unknown(asked_for), (
            f"preset {preset!r} names {', '.join(_unknown(asked_for))}, which this server has no "
            + "tool for, so it would resolve that many tools short. The tools it has are: "
            + f"{', '.join(TOOL_NAMES)}"
        )
    else:
        assert enabled is not None, "the assertion above leaves enabled set when preset is not"
        asked_for = _every_name_known(enabled)

    wanted = {ALWAYS_ON, *asked_for}
    modules = tuple(module for module in _TOOL_MODULES if module.TOOL_NAME in wanted)
    permissions = tuple(
        dict.fromkeys(permission for module in modules for permission in module.GRAPH_PERMISSIONS)
    )
    return Selection(
        preset=preset,
        tools=tuple(module.TOOL_NAME for module in modules),
        permissions=permissions,
        graph_scopes=tuple(graph_scope(permission) for permission in permissions),
    )


def _unknown(names: Iterable[str]) -> list[str]:
    return [name for name in names if name not in TOOL_NAMES]


def _every_name_known(enabled: Sequence[str]) -> tuple[str, ...]:
    unknown = _unknown(enabled)
    if unknown:
        raise ValueError(
            f"TOOLS_ENABLED names {', '.join(unknown)}, which this server has no tool for. "
            + f"The tools it has are: {', '.join(TOOL_NAMES)}"
        )
    return tuple(enabled)


def graph_advice(selection: Selection) -> Mapping[str, ToolAdvice]:
    return {
        module.TOOL_NAME: ToolAdvice(
            permissions=module.GRAPH_PERMISSIONS,
            not_found=_not_found_advice(module),
        )
        for module in _TOOL_MODULES
        if module.TOOL_NAME in selection.tools
    }


def _not_found_advice(module: ToolModule) -> str | None:
    return module.GRAPH_NOT_FOUND if isinstance(module, _NarrowsItsNotFound) else None


@dataclass(frozen=True, slots=True)
class GraphCallExample:
    arguments: Mapping[str, object]
    permissions: tuple[str, ...]


def graph_call_examples(selection: Selection) -> Mapping[str, GraphCallExample]:
    return {
        module.TOOL_NAME: GraphCallExample(
            arguments=module.GRAPH_CALL_EXAMPLE,
            permissions=_call_permissions(module),
        )
        for module in _TOOL_MODULES
        if module.TOOL_NAME in selection.tools
    }


def _call_permissions(module: ToolModule) -> tuple[str, ...]:
    if isinstance(module, _NarrowsItsCall):
        return module.GRAPH_CALL_NARROWS_TO
    return module.GRAPH_PERMISSIONS


def register_tools(mcp: FastMCP, transport: httpx.AsyncClient, selection: Selection) -> None:
    for module in _TOOL_MODULES:
        if module.TOOL_NAME in selection.tools:
            module.register(mcp, transport)
