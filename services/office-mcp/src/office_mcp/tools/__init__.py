"""The registry: every tool module, the selection an operator makes, and what it asks for.

A tool is one file. It publishes `TOOL_NAME` (str), `GRAPH_PERMISSIONS` (tuple) and `register`
(function). Adding a tool: one file plus one line here.

TRAP: the scope list must be derived from the modules, never hand-written. At startup,
`create_app` passes the selected tools' permissions to the auth provider. A permission not
consented at authorization time cannot be obtained later: the On-Behalf-Of exchange fails with
AADSTS65001 per tool call, before the tool body runs. Deriving it here guarantees every
registered tool has consent.

An operator chooses which of these tools run. `resolve` answers with both halves at once: the
modules to register, and the permissions to ask for. They are one object so they cannot disagree.
The filter runs here, before the union. FastMCP's `enable`/`disable` transforms would not do: they
hide a registered tool and leave its scopes computed, so they shorten `tools/list` and change
nothing the tenant is asked to grant.

Order is the registry's, never the operator's: `dict.fromkeys` over the modules in declaration
order, and the selection filtered over that same order. `TOOLS_ENABLED=a,b` and `b,a` must produce
one scope list, because the consent screen and every cached On-Behalf-Of token key are keyed by it.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx
from fastmcp import FastMCP

from office_mcp.shared.seam import ToolAdvice, graph_scope
from office_mcp.tools import get_me, list_chats, list_teams, read_message, search_messages

# The whole of what this package promises, and the reason it is entered through here: a caller
# that imported `tools/get_me.py` directly would be naming a tool module somewhere other than
# `_TOOL_MODULES`, which is the list every selection is filtered over and every scope derived from.
#
# `ToolModule` is deliberately not one of them. It is the contract a tool file satisfies, and the
# only place it can be checked is the `_TOOL_MODULES` annotation below — a tool file could not
# import it even to declare it, since reaching for `office_mcp.tools` from inside `tools/` is what
# layering rule 4 forbids. A name on the front door that nothing may walk through is a promise to
# nobody, so it stays private to this module and documents itself where it bites.
__all__ = [
    "ALWAYS_ON",
    "PRESETS",
    "TOOL_NAMES",
    "Selection",
    "graph_advice",
    "register_tools",
    "resolve",
]


class ToolModule(Protocol):
    """Contract a tool file must satisfy. Checked structurally: a missing `TOOL_NAME`,
    `GRAPH_PERMISSIONS` or `register` is a type error, not a runtime surprise.

    TRAP: `TOOL_NAME` is read-only here. A tool file writes it without an annotation, so its type is
    a literal string, and a mutable protocol attribute would demand exactly `str` — which would put
    an annotation on every tool file only to satisfy a type checker.
    """

    @property
    def TOOL_NAME(self) -> str: ...

    GRAPH_PERMISSIONS: tuple[str, ...]

    @staticmethod
    def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None: ...


@runtime_checkable
class _NarrowsItsNotFound(Protocol):
    """A tool that knows what a 404 on its own argument means, and says so instead of the default.

    Checked at runtime and kept out of `ToolModule`, because it is true of two tools out of ten. On
    the protocol every module has to satisfy it would be an attribute the other eight carried empty
    to satisfy a type checker — and the default advice is right for all eight, since their arguments
    are ids a caller passed in rather than handles this connector minted.
    """

    @property
    def GRAPH_NOT_FOUND(self) -> str: ...


# Every tool this server has, in the order they are registered and the order their permissions are
# asked for. One line per file, and the line is the whole of what adding a tool costs.
_TOOL_MODULES: tuple[ToolModule, ...] = (
    get_me,
    list_chats,
    list_teams,
    search_messages,
    read_message,
)

TOOL_NAMES: tuple[str, ...] = tuple(module.TOOL_NAME for module in _TOOL_MODULES)

# The tool every deployment runs, whatever it selected. `get_me` is how this server resolves "me" —
# its `user_id` is what message senders and meeting organisers are compared against, and other
# tools' prose sends a model to it — while `User.Read` is the least-privileged delegated permission
# Microsoft publishes and needs no administrator. So a preset need not name it, `TOOLS_ENABLED`
# lists only the rest, and the consequence to state plainly is that no deployment asks for zero
# permissions: every one asks for at least `User.Read`. This is the one hard-coded exception to
# "the selection is exactly these tools", and it is deliberate.
ALWAYS_ON: str = get_me.TOOL_NAME

# What each `TOOLS_PRESET` name means. The names themselves are `config.ToolsPreset`, so that a
# misspelling is a startup error listing the valid ones; the contents are here, because this is the
# only module that knows which tools exist. One test asserts the two sides agree in both directions,
# which is what keeps the names in config from becoming a second copy of the tool list.
PRESETS: Mapping[str, tuple[str, ...]] = {
    # Derived — "every tool there is" — so it needs no maintenance as tools land, and so the
    # widest surface stays a value an operator chose rather than one they inherited.
    "teams": TOOL_NAMES,
}


@dataclass(frozen=True)
class Selection:
    """One deployment's tool surface: what is registered, and what sign-in therefore asks for.

    `permissions` is Entra's own spelling, which is what an operator hands their administrator;
    `graph_scopes` is the same list as the authorize request carries it. Both are stored rather than
    one derived on demand, because the tuple handed to the auth provider is asserted by identity —
    a property rebuilding it per call would be a second list that merely looked equal.

    `preset` is how the surface was asked for and is `None` when it was listed out by hand. It rides
    along so the startup manifest can name the variable an operator would edit to change any of it.
    """

    preset: str | None
    tools: tuple[str, ...]
    permissions: tuple[str, ...]
    graph_scopes: tuple[str, ...]


def resolve(*, preset: str | None, enabled: Sequence[str] | None) -> Selection:
    """The surface `preset` or `enabled` names, filtered over the registry in the registry's order.

    Exactly one argument is the selection — `SurfaceConfig` is what refuses to start otherwise, so
    this asserts it rather than re-explaining it. `ALWAYS_ON` joins whatever was asked for, and
    naming it as well is accepted rather than an error: an operator who copies the manifest's tool
    list back into `TOOLS_ENABLED` will name it.

    **Both routes in are checked against the registry**, because a name this server has no tool for
    would otherwise be filtered out in silence — one tool fewer registered and one permission fewer
    on the consent screen than whoever wrote it believes. They differ only in whose mistake it is:
    a name in `TOOLS_ENABLED` is the operator's and gets an exception naming the tools that exist,
    while a name in a preset is ours and gets an assertion, because a mapping listing a tool this
    server does not have is a defect in this file rather than a deployment anyone asked for.
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
    """`enabled` unchanged, once every name in it is one this server actually has a tool for.

    A typo must never quietly cost a tool. `TOOLS_ENABLED=read_transcripts` would otherwise register
    one tool fewer and ask for one permission fewer than its operator believes, and the first sign
    of it would be a model that cannot find a tool the deployment is supposed to expose — long after
    the consent screen everyone already agreed to.
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

    Derived from the modules, exactly as the scope list above is, and for the same reason: a
    hand-written table would be a second copy of which permissions a tool calls under, and the two
    copies disagreeing is a 403 that sends an administrator after a permission that was never
    missing. Filtered by the selection, so it says nothing about a tool this deployment does not
    expose.

    `not_found` comes off the module the same way, for the two tools that publish one. The sentence
    a 404 needs instead of the default belongs to the tool that knows where its argument came
    from — a handle another tool minted cannot be a caller's typo — so the tool writes the prose and
    this reads it, rather than the wording living next to the failure in ten places.
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


def register_tools(mcp: FastMCP, transport: httpx.AsyncClient, selection: Selection) -> None:
    """Declare the selected tool modules against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` `create_app` built; each tool borrows it per
    call and none of them owns it.
    """
    for module in _TOOL_MODULES:
        if module.TOOL_NAME in selection.tools:
            module.register(mcp, transport)
