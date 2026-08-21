"""What this deployment resolved to, written for the person who has to act on it.

An operator chooses a tool surface, and Entra decides whether the sign-in that surface implies can
complete. **Nothing in this server can check the second against the first.** The session token's
`scp` carries only `access_as_user`, because Azure omits Graph scopes from it, so what the
registration grants is invisible here. A scope the registration does not carry fails at the
*authorize* hop: an unknown scope is rejected outright, and a real but unconsented admin-consent
permission sends the user to "Need admin approval". Either way it is a login nobody can complete,
with nothing in this server's logs, and the operator hears about it as a user complaint.

So this is the only place the exact ask is written down, and these lines are what an operator hands
their Entra administrator. It prints **no consent URL**. Provisioning the app registration is
deliberately not this service's job, `/.default` would consent to whatever the registration happens
to carry rather than to what this deployment asks for, and a scope-matched admin-consent URL needs a
`redirect_uri` matching a registered one. The only Web redirect URI office-mcp registers is
FastMCP's OAuth callback, which would render a *successful* consent as an error. The list is the
deliverable.

The description scan rides along, reporting tools whose prose points a model at a tool this
deployment does not expose. It only ever **warns**, and that is a decision rather than a shortcut.
The references are dense and mutual, so requiring every mention would drag `search_messages`, and
with it `ChannelMessage.Read.All` and an administrator's signature, into a deployment that asked
for nothing but `list_chats`. What the warning buys is that nobody is surprised a model was told
about a tool it cannot call.
"""

import re
import textwrap
from collections.abc import Mapping, Sequence
from typing import cast

from fastmcp import FastMCP
from fastmcp.tools import Tool

from office_mcp.tools import ALWAYS_ON, TOOL_NAMES, Selection

# Which delegated permissions Microsoft makes an administrator sign off, for every permission this
# connector is built to request. Not derived and not derivable: needing consent is Microsoft's rule
# about the permission, and no tool file knows it.
#
# The `False` entries are what make this checkable. One test asserts the table answers for every
# name in `REQUESTABLE_PERMISSIONS`, so a permission that arrives without a verdict is a failing
# test rather than a manifest quietly telling an operator no administrator is needed. A set holding
# only the names that need consent could not tell "no" from "nobody said".
#
# This is the one place a permission may be named before a tool declares it, and it is deliberately
# the opposite of the rule `REQUESTABLE_PERMISSIONS` keeps. Nothing here reaches an authorize
# request, so a name written early costs a manifest line at worst, where a name added early to what
# the connector *asks for* would wave through the spelling check that list exists to be.
NEEDS_ADMIN_CONSENT: Mapping[str, bool] = {
    "User.Read": False,
    "Chat.Read": False,
    "Team.ReadBasic.All": False,
    "Channel.ReadBasic.All": False,
    "ChannelMessage.Read.All": True,
    "OnlineMeetings.Read": False,
    "OnlineMeetingTranscript.Read.All": True,
    "OnlineMeetingRecording.Read.All": True,
}

# The column the values line up in, and the width the block wraps to. A tool list and a permission
# list both outgrow one line, and a hanging indent keeps them readable in a log record and in a
# terminal alike.
_LABEL_WIDTH = 17
_LINE_WIDTH = 96


async def surface_manifest(server: FastMCP, selection: Selection, *, version: str) -> str:
    """The resolved surface as an operator reads it: tools, permissions, who has to consent.

    Built on demand rather than captured at startup, so the route and the startup log line are the
    same text by construction rather than by a copy kept in step.
    """
    consent = tuple(
        permission for permission in selection.permissions if _needs_admin_consent(permission)
    )
    rows = [
        (
            "selection",
            f"TOOLS_PRESET={selection.preset}" if selection.preset is not None else "TOOLS_ENABLED",
        ),
        (f"tools ({len(selection.tools)})", ", ".join(_marked(selection.tools))),
        (f"permissions ({len(selection.permissions)})", ", ".join(selection.permissions)),
        ("admin consent", ", ".join(consent) if consent else "none"),
    ]
    rows.extend(("note", note) for note in _stale_promises(await server.list_tools(), selection))
    return "\n".join(
        [
            f"office-mcp {version} — resolved tool surface",
            *(_row(label, value) for label, value in rows),
        ]
    )


def _needs_admin_consent(permission: str) -> bool:
    verdict = NEEDS_ADMIN_CONSENT.get(permission)
    assert verdict is not None, (
        f"no admin-consent verdict for {permission}: NEEDS_ADMIN_CONSENT has to answer for every "
        + "permission a tool declares, or this manifest tells an operator an administrator is not "
        + "needed when one is, and every sign-in fails at 'Need admin approval' instead"
    )
    return verdict


def _marked(tools: Sequence[str]) -> list[str]:
    """The tool list, saying which entry no selection had to ask for."""
    return [f"{name} (always on)" if name == ALWAYS_ON else name for name in tools]


def _row(label: str, value: str) -> str:
    return "\n".join(
        textwrap.wrap(
            value,
            width=_LINE_WIDTH,
            initial_indent=f"  {label.ljust(_LABEL_WIDTH)}",
            subsequent_indent=" " * (2 + _LABEL_WIDTH),
        )
    )


def _stale_promises(tools: Sequence[Tool], selection: Selection) -> list[str]:
    """Where an exposed tool's prose points a model at a tool this deployment does not expose.

    `ALWAYS_ON` can never appear here, because it is registered whatever the selection is. That is
    what lets the tools that send a model to it go on saying so in every deployment.
    """
    absent = tuple(name for name in TOOL_NAMES if name not in selection.tools)
    notes: list[str] = []
    for tool in tools:
        prose = _prose_of(tool)
        named = [name for name in absent if _mentions(prose, name)]
        if named:
            notes.append(
                f"{tool.name}'s description mentions {', '.join(named)}, which this deployment "
                + "does not expose"
            )
    return notes


def _mentions(prose: str, name: str) -> bool:
    """Whether `prose` names the tool `name` as a whole word rather than as a substring.

    A tool name is one word to a reader and to this check: `read_message` is not mentioned by prose
    saying `read_messages`, and reporting it would be a note about a tool nobody referred to. Tool
    names are `[a-z_]`, so a word boundary lands where the eye does.
    """
    return re.search(rf"\b{re.escape(name)}\b", prose) is not None


def _prose_of(tool: Tool) -> str:
    """Everything a model reads of one tool: its own description and every one in its schemas.

    An argument's description is where a tool names the tool that mints its handle, so scanning the
    tool description alone would miss the references that matter most.
    """
    return " ".join(
        [
            tool.description or "",
            *_descriptions(tool.parameters),
            *_descriptions(tool.output_schema),
        ]
    )


def _descriptions(schema: Mapping[str, object] | None) -> list[str]:
    """Every `description` anywhere in a JSON schema: parameters, fields, nested objects."""
    if schema is None:
        return []
    found: list[str] = []
    pending: list[object] = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, Mapping):
            entries = cast("Mapping[str, object]", node)
            for key, value in entries.items():
                if key == "description" and isinstance(value, str):
                    found.append(value)
                else:
                    pending.append(value)
        elif isinstance(node, list):
            pending.extend(cast("Sequence[object]", node))
    return found
