"""This is the registry of all tools, the selection an operator makes, and the permissions that
the selection implies.

TRAP: derive the scope list from the modules. Never write it by hand. A permission that is not
consented at sign-in cannot be obtained later. The On-Behalf-Of exchange then fails with
AADSTS65001 on every tool call, before the tool body runs. FastMCP's `enable` and `disable`
transforms are no substitute for filtering here. They hide a registered tool but leave its scopes
computed.

Order always comes from the registry, never from the operator. It stays stable through
`dict.fromkeys`, not `set`. `TOOLS_ENABLED=a,b` and `b,a` must yield one scope list, because the
consent screen and every cached On-Behalf-Of token key are keyed by that list.
"""

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

# This is the whole of what this package promises. Importing `tools/get_me.py` directly names a
# tool module outside `_TOOL_MODULES`. That is the list every selection filters over, and the list
# every scope derives from. `ToolModule` does not appear in `__all__` on purpose.
# `tests/test_layering.py` rule 4 forbids a tool file from importing `office_365_mcp.tools`, so no
# tool file can name `ToolModule`, even to declare that it satisfies it.
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
    """This is the contract that a tool file satisfies. The `_TOOL_MODULES` annotation below checks
    it.

    TRAP: both read-only properties are read-only on purpose. A mutable protocol attribute demands
    an exact type, `str` or `Mapping[str, object]`, and tool files write these fields with no
    annotation.

    `GRAPH_CALL_EXAMPLE` holds arguments that reach Graph, so a startup probe can exercise the real
    call. Its ids are invented, but its shape is one the tool accepts. An argument that the tool
    rejects never reaches Graph, so it proves nothing. A tool with more than one reachable call
    names, in its own file, which call it picked.
    """

    @property
    def TOOL_NAME(self) -> str: ...

    GRAPH_PERMISSIONS: tuple[str, ...]

    @property
    def GRAPH_CALL_EXAMPLE(self) -> Mapping[str, object]: ...

    @staticmethod
    def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None: ...


@runtime_checkable
class _NarrowsItsNotFound(Protocol):
    """This marks a tool that knows what a 404 on its own argument means. Only a minority of tools
    need this, so the check happens at runtime.

    `ToolModule` leaves this out, because the default advice fits the rest. Their arguments are
    ids that a caller passed in, not handles that this connector minted.
    """

    @property
    def GRAPH_NOT_FOUND(self) -> str: ...


@runtime_checkable
class _NarrowsItsCall(Protocol):
    """This marks a tool whose `GRAPH_CALL_EXAMPLE` reaches Graph under fewer permissions than the
    tool declares.

    Only one tool out of all of them needs this, so the check happens at runtime and `ToolModule`
    leaves it out. `teams_read_message` exchanges for two permissions but reads one surface per
    call. So its chat example's refusal must name `Chat.Read`, not the channel permission.
    `narrowed_to` in `shared/seam.py` states the same rule for each call.
    """

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

# This joins every selection. `User.Read` is the least-privileged delegated permission that
# Microsoft publishes, and it needs no administrator consent. So no preset names `get_me`, and
# every deployment asks for at least `User.Read`. This is the one deliberate exception to the rule
# that the selection is exactly the named tools.
ALWAYS_ON: str = get_me.TOOL_NAME

# What each `config.ToolsPreset` name means.
#
# TRAP: permissions do not encode reachability. `teams-messages` without `teams_search_messages`
# asks for the same three permissions, and it exposes a `teams_read_message` that nothing in the
# preset can reach.
#
# TRAP: `teams` is written out here, not derived from `TOOL_NAMES`. A derived preset takes in
# every tool that joins the registry. So the first tool of another product puts its permission on
# the consent screen of every `teams` deployment, with no edit that anyone reviewed. Widening a
# live deployment costs every signed-in user a fresh sign-in.
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
    # Two axes, not one ladder. Mail content moves from read, to write, to send. Mailbox
    # configuration moves from read to write. The two axes are independent. Welding them into one
    # chain is how `outlook-automate` came to require `Mail.Send`. An out-of-office reply has
    # nothing to do with sending mail as the user, and a forwarding-rule audit has nothing to do
    # with reading one. Each row below asks for exactly what its own tools declare.
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
    """This is one deployment's tool surface: what is registered, and what sign-in therefore asks
    for.

    `permissions` uses Entra's own spelling. `graph_scopes` uses the authorize request's spelling.
    Both are stored, not derived on demand. The auth provider checks the tuple it receives by
    identity, not by equality. A property that rebuilds the tuple on each call only looks equal to
    it.
    """

    preset: str | None
    tools: tuple[str, ...]
    permissions: tuple[str, ...]
    graph_scopes: tuple[str, ...]


def resolve(*, preset: str | None, enabled: Sequence[str] | None) -> Selection:
    """This builds the surface that `preset` or `enabled` names, filtered over the registry in the
    registry's order.

    Both routes in are checked against the registry. Without that check, a name this server has no
    tool for is filtered out in silence. That leaves one tool fewer registered, and one permission
    fewer on the consent screen, than the person who wrote it expects. `TOOLS_ENABLED` raises an
    error because the mistake belongs to the operator. A preset asserts because the mistake
    belongs to this file.
    """
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
    """This returns `enabled` unchanged, once every name in it is known. A typo must never quietly
    cost a tool. If nothing catches the typo, `TOOLS_ENABLED=read_transcripts` registers one tool
    fewer and asks for one permission fewer than its operator expects.
    """
    unknown = _unknown(enabled)
    if unknown:
        raise ValueError(
            f"TOOLS_ENABLED names {', '.join(unknown)}, which this server has no tool for. "
            + f"The tools it has are: {', '.join(TOOL_NAMES)}"
        )
    return tuple(enabled)


def graph_advice(selection: Selection) -> Mapping[str, ToolAdvice]:
    """This is what `GraphAdviceMiddleware` uses to word each selected tool's refusals.

    This dictionary is derived from the modules. Writing it by hand instead creates a second copy
    of which permissions a tool calls under. A disagreement between the two copies causes a 403
    that sends an administrator after a permission that was never missing.
    """
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
    """This is one call through one tool that gets as far as a Graph request, plus what its refusal
    says.

    `arguments` must hold a call that the tool accepts. Arguments that the tool rejects never
    reach Graph at all.
    """

    arguments: Mapping[str, object]
    permissions: tuple[str, ...]


def graph_call_examples(selection: Selection) -> Mapping[str, GraphCallExample]:
    """This builds one refusable call per selected tool, derived from the modules exactly as the
    table above is.

    This function is exported, although nothing in `src/` calls it. It is the coverage contract
    for `tests/test_error_mapping.py`, which refuses every registered tool one by one. When that
    table was written by hand there instead, it became a second list of the tools. A tool
    registered before its row existed then left the file one tool short, which is the exact
    failure this file exists to prevent.
    """
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
    """This declares the selected tool modules against `transport`. Each module borrows
    `transport`. None of them owns it."""
    for module in _TOOL_MODULES:
        if module.TOOL_NAME in selection.tools:
            module.register(mcp, transport)
