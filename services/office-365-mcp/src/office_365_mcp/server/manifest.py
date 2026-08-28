"""What this deployment resolved to, written for the person who has to act on it.

**Nothing in this server can check the ask against the app registration.** The session token's `scp`
carries only `access_as_user`, because Azure omits Graph scopes from it. A scope the registration
does not carry fails at the *authorize* hop — an unknown scope outright, a real but unconsented
admin-consent permission at "Need admin approval" — with nothing in this server's logs either way.

It prints **no consent URL**: `/.default` would consent to whatever the registration happens to
carry rather than to what this deployment asks for, and a scope-matched admin-consent URL needs a
`redirect_uri` matching a registered one — and the only Web redirect URI office-365-mcp registers is
FastMCP's OAuth callback, which would render a *successful* consent as an error.

The description scan only ever **warns**: requiring every mention would drag
`teams_search_messages`, and
with it `ChannelMessage.Read.All` and an administrator's signature, into a deployment that asked for
nothing but `list_chats`.
"""

import re
import textwrap
from collections.abc import Mapping, Sequence
from typing import cast

from fastmcp import FastMCP
from fastmcp.tools import Tool

from office_365_mcp.tools import ALWAYS_ON, TOOL_NAMES, Selection

# Not derived and not derivable: needing consent is Microsoft's rule about the permission, and no
# tool file knows it. The `False` entries are what make the table checkable — one test asserts it
# answers for every name in `REQUESTABLE_PERMISSIONS`, and a set holding only the names that need
# consent could not tell "no" from "nobody said".
#
# Unlike `REQUESTABLE_PERMISSIONS`, a permission may be named here before a tool declares it:
# nothing here reaches an authorize request.
NEEDS_ADMIN_CONSENT: Mapping[str, bool] = {
    "User.Read": False,
    "Chat.Read": False,
    "Team.ReadBasic.All": False,
    "Channel.ReadBasic.All": False,
    "ChannelMessage.Read.All": True,
    "OnlineMeetings.Read": False,
    "OnlineMeetingTranscript.Read.All": True,
    "OnlineMeetingRecording.Read.All": True,
    # Microsoft publishes AdminConsentRequired: No for every delegated Mail permission. That is
    # Microsoft's rule about the permission and not a promise about a tenant: a tenant running a
    # restricted user-consent policy still stops an unprivileged user at "Need admin approval".
    "Mail.Read": False,
    "People.Read": False,
    "MailboxSettings.Read": False,
}

_LABEL_WIDTH = 17
_LINE_WIDTH = 96


async def surface_manifest(server: FastMCP, selection: Selection, *, version: str) -> str:
    """Built on demand, so the `/manifest` route and the startup log line are the same text."""
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
            f"office-365-mcp {version} — resolved tool surface",
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
    """`ALWAYS_ON` can never appear here, because it is registered whatever the selection is, which
    is what lets the tools that send a model to it go on saying so in every deployment."""
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
    """Whole word, not substring: `teams_read_message` is not mentioned by prose saying
    `read_messages`.
    Tool names are `[a-z_]`, so a word boundary lands where the eye does."""
    return re.search(rf"\b{re.escape(name)}\b", prose) is not None


def _prose_of(tool: Tool) -> str:
    """An argument's description is where a tool names the tool that mints its handle, so scanning
    the tool description alone would miss the references that matter most."""
    return " ".join(
        [
            tool.description or "",
            *_descriptions(tool.parameters),
            *_descriptions(tool.output_schema),
        ]
    )


def _descriptions(schema: Mapping[str, object] | None) -> list[str]:
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
