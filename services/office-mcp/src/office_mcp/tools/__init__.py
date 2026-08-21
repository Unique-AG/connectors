"""The registry of all tools, the selection an operator makes, and the permissions it implies.

Each tool is one file that publishes `TOOL_NAME`, `GRAPH_PERMISSIONS`, `GRAPH_CALL_EXAMPLE` and
`register`. Adding a tool costs one file plus one line here.

TRAP: Derive the scope list from the modules, never hand-write it. `create_app` passes the selected
tools' permissions to the auth provider at startup, and a permission not consented at sign-in
cannot be obtained later: the On-Behalf-Of exchange fails with AADSTS65001 on every tool call,
before the tool body runs. Deriving it here guarantees every registered tool has consent.

`resolve` answers a selection with both halves at once: the modules to register, and the permissions
to ask for. One object, so they cannot disagree. The filter runs here, before the union, because
FastMCP's `enable` and `disable` transforms hide a registered tool and leave its scopes computed.
They shorten `tools/list` and change nothing the tenant is asked to grant.

Order is stable (via `dict.fromkeys`, not `set`) and is the registry's, never the operator's:
`TOOLS_ENABLED=a,b` and `b,a` produce one scope list, which the consent screen and every cached
On-Behalf-Of token key are keyed by.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx
from fastmcp import FastMCP

from office_mcp.shared.seam import ToolAdvice, graph_scope
from office_mcp.tools import (
    browse_channel,
    get_me,
    list_channels,
    list_chats,
    list_meeting_recordings,
    list_meeting_transcripts,
    list_teams,
    read_message,
    read_transcript,
    search_messages,
)

# The whole of what this package promises, and the reason it is entered through here: a caller
# importing `tools/get_me.py` directly would name a tool module outside `_TOOL_MODULES`, the list
# every selection is filtered over and every scope derived from.
#
# `ToolModule` is deliberately not on it. It is the contract a tool file satisfies, and the only
# place it can be checked is the `_TOOL_MODULES` annotation below. A tool file cannot import it
# even to declare it: reaching for `office_mcp.tools` from inside `tools/` is what layering rule 4
# forbids. Exporting a name nothing may import would promise nobody anything, so it stays private.
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
    """Contract a tool must satisfy. Type-checked structurally at import.

    TRAP: `TOOL_NAME` is read-only. A tool file writes it without an annotation, so its type is a
    literal string, and a mutable protocol attribute would demand exactly `str`: an annotation on
    every tool file only to satisfy a type checker.
    """

    @property
    def TOOL_NAME(self) -> str: ...

    GRAPH_PERMISSIONS: tuple[str, ...]

    # Read-only for the same reason `TOOL_NAME` is: a tool file writes a dict literal, and a
    # mutable protocol attribute would demand exactly `Mapping[str, object]` on every tool file.
    # Read-only leaves the annotation to the tool file.
    @property
    def GRAPH_CALL_EXAMPLE(self) -> Mapping[str, object]: ...

    @staticmethod
    def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None: ...


@runtime_checkable
class _NarrowsItsNotFound(Protocol):
    """A tool that knows what a 404 on its own argument means, and says so instead of the default.

    Checked at runtime and kept out of `ToolModule`, because it is true of two tools out of ten. On
    the protocol every module satisfies, the other eight would carry it empty for a type checker,
    and the default advice is right for all eight: their arguments are ids a caller passed in, not
    handles this connector minted.
    """

    @property
    def GRAPH_NOT_FOUND(self) -> str: ...


@runtime_checkable
class _NarrowsItsCall(Protocol):
    """A tool whose `GRAPH_CALL_EXAMPLE` reaches Graph under fewer permissions than it declares.

    True of one tool out of ten, so it is checked at runtime and kept off `ToolModule` for the same
    reason `_NarrowsItsNotFound` is. `read_message` is exchanged for two permissions and reads one
    surface per call, and its example call names a chat, so the refusal that example earns names
    `Chat.Read` and must not name the channel permission. `narrowed_to` in `shared/seam.py` makes
    the same statement per call at run time.
    """

    @property
    def GRAPH_CALL_NARROWS_TO(self) -> tuple[str, ...]: ...


# Every tool this server has, in the order they register and their permissions are asked for.
_TOOL_MODULES: tuple[ToolModule, ...] = (
    get_me,
    list_chats,
    list_teams,
    list_channels,
    browse_channel,
    search_messages,
    read_message,
    list_meeting_transcripts,
    read_transcript,
    list_meeting_recordings,
)

TOOL_NAMES: tuple[str, ...] = tuple(module.TOOL_NAME for module in _TOOL_MODULES)

# The tool every deployment runs, whatever it selected. `get_me` is how this server resolves "me":
# its `user_id` is what message senders and meeting organisers are compared against, and other
# tools' prose sends a model to it. `User.Read` is the least-privileged delegated permission
# Microsoft publishes and needs no administrator, so a preset need not name `get_me` and
# `TOOLS_ENABLED` lists only the rest. Every deployment therefore asks for at least `User.Read`.
# That is the one deliberate exception to "the selection is exactly these tools".
ALWAYS_ON: str = get_me.TOOL_NAME

# What each `TOOLS_PRESET` name means. The names are `config.ToolsPreset`, so a misspelling is a
# startup error listing the valid ones. The contents are here, because this is the only module that
# knows which tools exist. One test asserts the two sides agree in both directions, so config's
# names cannot become a second copy of the tool list.
#
# Each curated preset is one use case, the tools it needs and no others, so its permissions are the
# smallest set that use case can run on. None lists `ALWAYS_ON`, which joins every selection anyway.
# Two checks live elsewhere: `resolve` refuses a preset naming a tool this server lacks, and one
# test per preset asserts every tool in it can get its arguments from another member. Permissions
# do not encode reachability: `teams-messages` without `search_messages` asks for the identical
# three permissions and exposes a `read_message` nothing in it can address.
PRESETS: Mapping[str, tuple[str, ...]] = {
    # `TOOL_NAMES` rather than a list, so it needs no maintenance as tools land and the widest
    # surface stays a value an operator chose rather than one they inherited.
    "teams": TOOL_NAMES,
    "teams-chat": ("list_chats",),
    "teams-messages": ("list_chats", "search_messages", "read_message"),
    "teams-channels": ("list_teams", "list_channels", "browse_channel"),
    "teams-transcripts": ("list_chats", "list_meeting_transcripts", "read_transcript"),
    "teams-recordings": ("list_chats", "list_meeting_recordings"),
    "teams-meetings": (
        "list_chats",
        "list_meeting_transcripts",
        "read_transcript",
        "list_meeting_recordings",
    ),
}


@dataclass(frozen=True, slots=True)
class Selection:
    """One deployment's tool surface: what is registered, and what sign-in therefore asks for.

    `permissions` is Entra's own spelling, the one an operator hands their administrator, and
    `graph_scopes` is the same list as the authorize request carries it. Both are stored rather than
    one derived on demand: the tuple handed to the auth provider is asserted by identity, and a
    property rebuilding it per call would be a second list that merely looked equal.

    `preset` is how the surface was asked for, and `None` when it was listed out by hand. It rides
    along so the startup manifest can name the variable an operator would edit.
    """

    preset: str | None
    tools: tuple[str, ...]
    permissions: tuple[str, ...]
    graph_scopes: tuple[str, ...]


def resolve(*, preset: str | None, enabled: Sequence[str] | None) -> Selection:
    """The surface `preset` or `enabled` names, filtered over the registry in the registry's order.

    Exactly one argument is the selection. `SurfaceConfig` refuses to start otherwise, so this
    asserts it rather than re-explaining it. `ALWAYS_ON` joins whatever was asked for, and naming it
    as well is accepted: an operator who copies the manifest's tool list back into `TOOLS_ENABLED`
    will name it.

    Both routes in are checked against the registry, because a name this server has no tool for
    would otherwise be filtered out in silence, leaving one tool fewer registered and one permission
    fewer on the consent screen than whoever wrote it believes. The two routes differ only in whose
    mistake it is: a name in `TOOLS_ENABLED` is the operator's and raises, while a name in a preset
    is ours and asserts: a mapping listing a tool this server lacks is a defect in this file.
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
    """The names in `names` this server has no tool for, in the order they were written."""
    return [name for name in names if name not in TOOL_NAMES]


def _every_name_known(enabled: Sequence[str]) -> tuple[str, ...]:
    """`enabled` unchanged, once every name in it is one this server has a tool for.

    A typo must never quietly cost a tool. `TOOLS_ENABLED=read_transcripts` would otherwise register
    one tool fewer and ask for one permission fewer than its operator believes, and the first sign
    would be a model that cannot find a tool the deployment should expose, long after the consent
    screen everyone agreed to.
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

    Derived from the modules for the same reason the scope list above is: a hand-written table
    would be a second copy of which permissions a tool calls under, and two copies disagreeing is a
    403 that sends an administrator after a permission that was never missing. Filtered by the
    selection, so it says nothing about a tool this deployment does not expose.

    `not_found` comes off the module the same way, for the two tools that publish one. The sentence
    a 404 needs instead of the default belongs to the tool that knows where its argument came from,
    because a handle another tool minted cannot be a caller's typo. The tool writes the prose and
    this function reads it, rather than the wording living next to the failure in ten places.
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
    """The sentence this tool's 404 needs, or `None` to leave the default one in place."""
    return module.GRAPH_NOT_FOUND if isinstance(module, _NarrowsItsNotFound) else None


@dataclass(frozen=True, slots=True)
class GraphCallExample:
    """One call through one tool that gets as far as a Graph request, and what its refusal says.

    `arguments` is a call the tool accepts, because arguments it rejects never reach Graph at all.
    `permissions` is what a refusal of that call has to name: the tool's declared tuple, or the
    fewer permissions it says this call is made under.
    """

    arguments: Mapping[str, object]
    permissions: tuple[str, ...]


def graph_call_examples(selection: Selection) -> Mapping[str, GraphCallExample]:
    """One refusable call per selected tool, derived from the modules exactly as the table above is.

    Exported although nothing in `src/` calls it: it is the coverage contract for
    `tests/test_error_mapping.py`, which refuses every registered tool one by one and asserts each
    reads back as the advice for its own permissions. Hand-written there, the table was a second
    list of the tools. A tool registered before its row existed left the file one tool short, the
    very failure the file exists to prevent, and split a tool's arrival from its coverage across two
    commits. Published here, the row travels in the tool's own file, `ToolModule` makes a tool
    without one a type error rather than a red test, and coverage of the registered surface is this
    mapping's keys by construction. A test reaching `_TOOL_MODULES` instead would name every tool
    module in a second place, and being that one place is what this module is for.
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
    """The permissions this tool's example call is made under, not always the ones it declares."""
    if isinstance(module, _NarrowsItsCall):
        return module.GRAPH_CALL_NARROWS_TO
    return module.GRAPH_PERMISSIONS


def register_tools(mcp: FastMCP, transport: httpx.AsyncClient, selection: Selection) -> None:
    """Declare the selected tool modules against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` `create_app` built. Each tool borrows it per
    call and none of them owns it.
    """
    for module in _TOOL_MODULES:
        if module.TOOL_NAME in selection.tools:
            module.register(mcp, transport)
