"""The registry: every tool module, and the one thing that has to be assembled from all of them.

A tool is a file. It owns its name, the prose that teaches a model when to reach for it, the Graph
delegated permissions it calls under, its arguments and their descriptions, the shape it answers
with, the Graph request it makes and the wording of every refusal only it can explain. Adding the
fifth tool is adding one file and one line to `_TOOL_MODULES`; reading the fourth is reading one
file. Nothing here is a base class and nothing is a decorator of our own — a tool module publishes
two names (`GRAPH_PERMISSIONS` and `register`) and that is the whole of the contract, which is what
`ToolModule` says in the only place it could be checked.

**This is the one piece of central machinery, and `GRAPH_SCOPES` is why it exists.** `create_app`
has to hand the auth provider every Graph permission any tool might redeem, at startup, before any
tool has been called: a permission the user (or an administrator) never consented to cannot be
obtained later — the On-Behalf-Of exchange fails with AADSTS65001 before the tool body runs. So the
union is assembled here, *from the modules*, and never written by hand. A hand-written list is a
list somebody forgets: the fifth tool file would be added, registered, called, and refused at
sign-in for a permission nobody asked for. Deriving it means a tool that is registered has its
permissions consented to by construction.

The order is stable across process starts, and that is deliberate rather than tidy: `dict.fromkeys`
over the modules in declaration order rather than a `set`, because two tools sharing a permission
must not make the scope list a different string every time the process comes up — the consent
screen and every cached On-Behalf-Of token key change with it.

Two tools naming the same permission is normal and is not duplication to remove: `list_chats`,
`search_messages` and `read_message` all spend `Chat.Read`, because a chat's messages are read under
it whether they are being listed, searched or read one at a time, and the last two both spend
`ChannelMessage.Read.All` for the channel side of the same question. Each has to declare what its
own request is made under, because that tuple is also what its 403 and its AADSTS65001 are worded
from. Deduplication is this module's job, not theirs, and doing it here is what lets a tool arrive
without knowing which others exist.
"""

from typing import Protocol

import httpx
from fastmcp import FastMCP

from office_mcp.shared.seam import graph_scope
from office_mcp.tools import get_me, list_chats, read_message, search_messages

# The whole of what this package promises, and the reason it is entered through here: a caller
# that imported `tools/get_me.py` directly would be naming a tool module somewhere other than
# `_TOOL_MODULES`, which is the list `GRAPH_SCOPES` is derived from. Both names are `app.py`'s.
#
# `ToolModule` is deliberately not one of them. It is the contract a tool file satisfies, and the
# only place it can be checked is the `_TOOL_MODULES` annotation below — a tool file could not
# import it even to declare it, since reaching for `office_mcp.tools` from inside `tools/` is what
# layering rule 4 forbids. A name on the front door that nothing may walk through is a promise to
# nobody, so it stays private to this module and documents itself where it bites.
__all__ = ["GRAPH_SCOPES", "register_tools"]


class ToolModule(Protocol):
    """What a tool file has to publish to be registered, and nothing more.

    A `Protocol` rather than a convention in a docstring because modules are checked against it
    structurally: a file added to `_TOOL_MODULES` without a `GRAPH_PERMISSIONS` or without a
    `register` is a type error at the line that lists it, rather than an `AttributeError` at
    startup or — worse — a permission missing from the consent screen.
    """

    GRAPH_PERMISSIONS: tuple[str, ...]

    @staticmethod
    def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None: ...


# Every tool this server exposes, in the order they are registered and the order their permissions
# are asked for. One line per file, and the line is the whole of what adding a tool costs.
_TOOL_MODULES: tuple[ToolModule, ...] = (get_me, list_chats, search_messages, read_message)

# What sign-in must ask Entra for, so that every tool's On-Behalf-Of exchange has something to
# redeem. Derived from the modules above — see the module docstring for why it may never be
# written out by hand, and why `dict.fromkeys` rather than a set.
GRAPH_SCOPES: tuple[str, ...] = tuple(
    dict.fromkeys(
        graph_scope(permission)
        for module in _TOOL_MODULES
        for permission in module.GRAPH_PERMISSIONS
    )
)


def register_tools(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare every tool module against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` `create_app` built; each tool borrows it per
    call and none of them owns it.
    """
    for module in _TOOL_MODULES:
        module.register(mcp, transport)
