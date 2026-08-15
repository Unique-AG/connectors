"""The registry: every tool module, and the one thing that has to be assembled from all of them.

A tool is a file. It owns its name, the prose that teaches a model when to reach for it, the Graph
delegated permissions it calls under, its arguments and their descriptions, the shape it answers
with, the Graph request it makes and the wording of every refusal only it can explain. Adding the
fourth tool is adding one file and one line to `_TOOL_MODULES`; reading the third is reading one
file. Nothing here is a base class and nothing is a decorator of our own — a tool module publishes
three names (`TOOL_NAME`, `GRAPH_PERMISSIONS` and `register`) and that is the whole of the contract,
which is what `ToolModule` says in the only place it could be checked. All three were already on
every tool file before an operator could select between them; nothing had to be added to one.

**This is the one piece of central machinery, and the scope list is why it exists.** `create_app`
has to hand the auth provider every Graph permission any registered tool might redeem, at startup,
before any tool has been called: a permission the user (or an administrator) never consented to
cannot be obtained later — the On-Behalf-Of exchange fails with AADSTS65001 before the tool body
runs. So the union is assembled here, *from the modules*, and never written by hand. A hand-written
list is a list somebody forgets: the fourth tool file would be added, registered, called, and
refused at sign-in for a permission nobody asked for. Deriving it means a tool that is registered
has its permissions consented to by construction.

**An operator chooses which of these tools a deployment runs**, and `resolve` is where that choice
becomes both halves of the answer at once: the modules to register and the permissions to ask for.
The two are one object because they must not be able to disagree — a tool registered whose
permission was not requested fails at its first call, and a permission requested for a tool nobody
registered widens every user's consent screen for nothing. So the filter happens *here*, before the
union is taken. Hiding a tool afterwards would not do: FastMCP's `enable`/`disable` transforms leave
the module registered and the scopes already computed, so they shorten `tools/list` and change
nothing whatever about what the tenant is asked to grant.

The order is the registry's own and never the operator's, and that is load-bearing rather than tidy:
`dict.fromkeys` over the modules in declaration order rather than a `set`, and the selection
filtered over that same order, because `TOOLS_ENABLED=a,b` and `b,a` must not make the scope list a
different string — the consent screen and every cached On-Behalf-Of token key are keyed by it.

Two tools naming the same permission is normal and is not duplication to remove: `list_chats` and
`search_messages` both spend `Chat.Read`, because a chat's messages are read under it whether they
are being listed or searched, and the tools that read a channel message will spend
`search_messages`'s `ChannelMessage.Read.All`. Each has to declare what its own request is made
under, because that tuple is also what its 403 and its AADSTS65001 are worded from. Deduplication is
this module's job, not theirs, and doing it here is what lets a tool arrive without knowing which
others exist.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx
from fastmcp import FastMCP

from office_mcp.shared.seam import ToolAdvice, graph_scope
from office_mcp.tools import get_me, list_chats, search_messages

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
    """What a tool file has to publish to be registered, and nothing more.

    A `Protocol` rather than a convention in a docstring because modules are checked against it
    structurally: a file added to `_TOOL_MODULES` without a `TOOL_NAME`, a `GRAPH_PERMISSIONS` or a
    `register` is a type error at the line that lists it, rather than an `AttributeError` at
    startup or — worse — a permission missing from the consent screen.

    `TOOL_NAME` is read as well as the permissions because a selection is written in tool names.
    Every tool file already published it, to name itself to FastMCP; nothing had to be added to one.
    It is declared read-only — a property rather than an attribute — because a tool file writes
    `TOOL_NAME = "get_me"` without an annotation, so its type is the literal string and a *mutable*
    protocol attribute would demand exactly `str`. Nothing here writes it, and requiring an
    annotation on every tool file to satisfy a type checker would be the tool files serving this
    module rather than the other way round.
    """

    @property
    def TOOL_NAME(self) -> str: ...

    GRAPH_PERMISSIONS: tuple[str, ...]

    @staticmethod
    def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None: ...


# Every tool this server has, in the order they are registered and the order their permissions are
# asked for. One line per file, and the line is the whole of what adding a tool costs.
_TOOL_MODULES: tuple[ToolModule, ...] = (get_me, list_chats, search_messages)

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

    `not_found` is left unset here. The sentence a 404 needs instead of the default belongs to the
    tool that knows where its argument came from, and while a tool still opens its own mapping block
    that is where it says it.
    """
    return {
        module.TOOL_NAME: ToolAdvice(permissions=module.GRAPH_PERMISSIONS)
        for module in _TOOL_MODULES
        if module.TOOL_NAME in selection.tools
    }


def register_tools(mcp: FastMCP, transport: httpx.AsyncClient, selection: Selection) -> None:
    """Declare the selected tool modules against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` `create_app` built; each tool borrows it per
    call and none of them owns it.
    """
    for module in _TOOL_MODULES:
        if module.TOOL_NAME in selection.tools:
            module.register(mcp, transport)
