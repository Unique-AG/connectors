"""The registry of all tools, the selection an operator makes, and the permissions it implies.

TRAP: derive the scope list from the modules, never hand-write it. A permission not consented at
sign-in cannot be obtained later — the On-Behalf-Of exchange fails with AADSTS65001 on every tool
call, before the tool body runs. FastMCP's `enable` and `disable` transforms are no substitute for
filtering here: they hide a registered tool and leave its scopes computed.

Order is the registry's, never the operator's, and stable via `dict.fromkeys` rather than `set`:
`TOOLS_ENABLED=a,b` and `b,a` must yield one scope list, which the consent screen and every cached
On-Behalf-Of token key are keyed by.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx
from fastmcp import FastMCP

from office_365_mcp.shared.seam import ToolAdvice, graph_scope
from office_365_mcp.tools import (
    browse_channel,
    get_me,
    list_channels,
    list_chats,
    list_meeting_recordings,
    list_meeting_transcripts,
    list_teams,
    outlook_browse_folders,
    outlook_find_recipient,
    outlook_get_mailbox_settings,
    outlook_list_mail,
    outlook_mark_mail,
    outlook_move_mail,
    outlook_read_mail,
    outlook_read_thread,
    outlook_search_mail,
    read_transcript,
    teams_read_message,
    teams_search_messages,
)

# The whole of what this package promises: importing `tools/get_me.py` directly names a tool module
# outside `_TOOL_MODULES`, the list every selection is filtered over and every scope derived from.
# `ToolModule` is absent on purpose — `tests/test_layering.py` rule 4 forbids a tool file from
# importing `office_365_mcp.tools`, so no tool file may name it even to declare it.
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
    """Contract a tool file satisfies, checked at the `_TOOL_MODULES` annotation below.

    TRAP: both read-only properties are read-only on purpose. A mutable protocol attribute would
    demand exactly `str` or `Mapping[str, object]`, and tool files write these unannotated.
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
    """A tool that knows what a 404 on its own argument means. Two tools of ten, so runtime-checked.

    Off `ToolModule` because the default advice is right for the other eight: their arguments are
    ids a caller passed in, not handles this connector minted.
    """

    @property
    def GRAPH_NOT_FOUND(self) -> str: ...


@runtime_checkable
class _NarrowsItsCall(Protocol):
    """A tool whose `GRAPH_CALL_EXAMPLE` reaches Graph under fewer permissions than it declares.

    One tool of ten, so runtime-checked and off `ToolModule`. `teams_read_message` is exchanged for
    two
    permissions and reads one surface per call, so its chat example's refusal must name `Chat.Read`
    and not the channel permission. `narrowed_to` in `shared/seam.py` says the same per call.
    """

    @property
    def GRAPH_CALL_NARROWS_TO(self) -> tuple[str, ...]: ...


_TOOL_MODULES: tuple[ToolModule, ...] = (
    get_me,
    list_chats,
    list_teams,
    list_channels,
    browse_channel,
    teams_search_messages,
    teams_read_message,
    list_meeting_transcripts,
    read_transcript,
    list_meeting_recordings,
    outlook_search_mail,
    outlook_read_mail,
    outlook_browse_folders,
    outlook_find_recipient,
    outlook_read_thread,
    outlook_list_mail,
    outlook_get_mailbox_settings,
    outlook_mark_mail,
    outlook_move_mail,
)

TOOL_NAMES: tuple[str, ...] = tuple(module.TOOL_NAME for module in _TOOL_MODULES)

# Joins every selection. `User.Read` is the least-privileged delegated permission Microsoft
# publishes and needs no administrator, so no preset names `get_me` and every deployment asks for
# at least `User.Read` — the one deliberate exception to "the selection is exactly these tools".
ALWAYS_ON: str = get_me.TOOL_NAME

# What each `config.ToolsPreset` name means.
# TRAP: permissions do not encode reachability. `teams-messages` without `teams_search_messages`
# asks for
# the identical three permissions and exposes a `teams_read_message` nothing in it can address.
# TRAP: `teams` is written out rather than derived from `TOOL_NAMES`. A derived preset takes in
# every tool that joins the registry, so the first tool of another product would put its permission
# on the consent screen of every `teams` deployment without an edit anybody reviewed — and widening
# a live deployment costs every signed-in user a fresh sign-in.
PRESETS: Mapping[str, tuple[str, ...]] = {
    "teams": (
        "list_chats",
        "list_teams",
        "list_channels",
        "browse_channel",
        "teams_search_messages",
        "teams_read_message",
        "list_meeting_transcripts",
        "read_transcript",
        "list_meeting_recordings",
    ),
    "teams-chat": ("list_chats",),
    "teams-messages": ("list_chats", "teams_search_messages", "teams_read_message"),
    "teams-channels": ("list_teams", "list_channels", "browse_channel"),
    "teams-transcripts": ("list_chats", "list_meeting_transcripts", "read_transcript"),
    "teams-recordings": ("list_chats", "list_meeting_recordings"),
    "teams-meetings": (
        "list_chats",
        "list_meeting_transcripts",
        "read_transcript",
        "list_meeting_recordings",
    ),
    "outlook-read": (
        "outlook_search_mail",
        "outlook_read_mail",
        "outlook_browse_folders",
        "outlook_find_recipient",
        "outlook_read_thread",
        "outlook_list_mail",
    ),
    "outlook-mailbox": (
        "outlook_search_mail",
        "outlook_read_mail",
        "outlook_browse_folders",
        "outlook_find_recipient",
        "outlook_read_thread",
        "outlook_list_mail",
        "outlook_get_mailbox_settings",
    ),
    "outlook-write": (
        "outlook_search_mail",
        "outlook_read_mail",
        "outlook_browse_folders",
        "outlook_find_recipient",
        "outlook_read_thread",
        "outlook_list_mail",
        "outlook_get_mailbox_settings",
        "outlook_mark_mail",
        "outlook_move_mail",
    ),
}


@dataclass(frozen=True, slots=True)
class Selection:
    """One deployment's tool surface: what is registered, and what sign-in therefore asks for.

    `permissions` is Entra's own spelling and `graph_scopes` is the authorize request's. Both are
    stored rather than one derived on demand: the tuple handed to the auth provider is asserted by
    identity, and a property rebuilding it per call would merely look equal.
    """

    preset: str | None
    tools: tuple[str, ...]
    permissions: tuple[str, ...]
    graph_scopes: tuple[str, ...]


def resolve(*, preset: str | None, enabled: Sequence[str] | None) -> Selection:
    """The surface `preset` or `enabled` names, filtered over the registry in the registry's order.

    Both routes in are checked against the registry, because a name this server has no tool for
    would otherwise be filtered out in silence, leaving one tool fewer registered and one permission
    fewer on the consent screen than whoever wrote it believes. `TOOLS_ENABLED` raises because the
    mistake is the operator's; a preset asserts because the mistake is this file's.
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
    """`enabled` unchanged, once every name is known. A typo must never quietly cost a tool:
    `TOOLS_ENABLED=read_transcripts` would register one tool fewer and ask for one permission
    fewer than its operator believes.
    """
    unknown = _unknown(enabled)
    if unknown:
        raise ValueError(
            f"TOOLS_ENABLED names {', '.join(unknown)}, which this server has no tool for. "
            + f"The tools it has are: {', '.join(TOOL_NAMES)}"
        )
    return tuple(enabled)


def graph_advice(selection: Selection) -> Mapping[str, ToolAdvice]:
    """What `GraphAdviceMiddleware` words each selected tool's refusals from.

    Derived from the modules: a hand-written table would be a second copy of which permissions a
    tool calls under, and two copies disagreeing is a 403 that sends an administrator after a
    permission that was never missing.
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
    """One call through one tool that gets as far as a Graph request, and what its refusal says.

    `arguments` must be a call the tool accepts; arguments it rejects never reach Graph at all.
    """

    arguments: Mapping[str, object]
    permissions: tuple[str, ...]


def graph_call_examples(selection: Selection) -> Mapping[str, GraphCallExample]:
    """One refusable call per selected tool, derived from the modules exactly as the table above is.

    Exported although nothing in `src/` calls it: it is the coverage contract for
    `tests/test_error_mapping.py`, which refuses every registered tool one by one. Hand-written
    there, the table was a second list of the tools, and a tool registered before its row existed
    left the file one tool short — the very failure that file exists to prevent.
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
    """Declare the selected tool modules against `transport`, which each borrows and none owns."""
    for module in _TOOL_MODULES:
        if module.TOOL_NAME in selection.tools:
            module.register(mcp, transport)
