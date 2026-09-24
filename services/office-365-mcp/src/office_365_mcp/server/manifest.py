"""What this deployment resolved to, written for the person who must act on it.

**Nothing in this server can check the ask against the app registration.** The session token's `scp`
carries only `access_as_user`, because Azure omits Graph scopes from it. A scope that the
registration does not carry fails at the *authorize* hop. An unknown scope fails outright. A real
but unconsented admin-consent permission stops at "Need admin approval". Neither failure appears in
this server's logs.

It prints **no consent URL**. `/.default` consents to whatever the registration happens to carry,
not to what this deployment asks for. A scope-matched admin-consent URL also needs a `redirect_uri`
that matches a registered one. The only Web redirect URI that office-365-mcp registers is FastMCP's
OAuth callback, and that callback treats a *successful* consent as an error.

The description scan only ever **warns**. If it required every mention instead, it drags
`teams_search_messages`, together with `ChannelMessage.Read.All` and an administrator's signature,
into a deployment that asked for nothing but `teams_list_chats`.
"""

import re
import textwrap
from collections.abc import Mapping, Sequence
from typing import cast

from fastmcp import FastMCP
from fastmcp.tools import Tool

from office_365_mcp.tools import ALWAYS_ON, TOOL_NAMES, Selection

# This table is not derived, and it cannot be derived. Whether a permission needs consent is
# Microsoft's rule about that permission, and no tool file records it. The `False` entries make the
# table checkable: one test asserts that it answers for every name in `REQUESTABLE_PERMISSIONS`. A
# set that holds only the names that need consent cannot tell "no" from "nobody said".
#
# Unlike `REQUESTABLE_PERMISSIONS`, this table can name a permission before a tool declares it.
# Nothing here reaches an authorize request.
NEEDS_ADMIN_CONSENT: Mapping[str, bool] = {
    "User.Read": False,
    "Chat.Read": False,
    "Team.ReadBasic.All": False,
    "Channel.ReadBasic.All": False,
    "ChannelMessage.Read.All": True,
    # Microsoft publishes AdminConsentRequired: No for both permissions below. This comes from the
    # permissions reference, not copied from a neighboring row. `ChannelMessage.Read.All` above
    # needs consent because it has the ".All" shape and reads every channel in the tenant. The two
    # permissions below are narrower, delegated-only sends that touch only what the signed-in user
    # can already post by hand.
    "ChatMessage.Send": False,
    "ChannelMessage.Send": False,
    "OnlineMeetings.Read": False,
    "OnlineMeetingTranscript.Read.All": True,
    "OnlineMeetingRecording.Read.All": True,
    # Microsoft publishes AdminConsentRequired: No for every delegated Mail permission. That is
    # Microsoft's rule about the permission, not a promise about a tenant. A tenant that runs a
    # restricted user-consent policy still stops an unprivileged user at "Need admin approval".
    "Mail.Read": False,
    "People.Read": False,
    "MailboxSettings.Read": False,
    "Mail.ReadWrite": False,
    "Mail.Send": False,
    "Mail.ReadBasic": False,
    "MailboxSettings.ReadWrite": False,
    # Microsoft publishes AdminConsentRequired: No for every delegated Calendars permission. This
    # includes both `.Shared` permissions.
    "Calendars.Read": False,
    "Calendars.Read.Shared": False,
    "Calendars.ReadWrite": False,
    "Calendars.ReadWrite.Shared": False,
    "Files.Read.All": True,
    "Notes.Read": False,
    "Notes.Create": False,
    "Notes.ReadWrite": False,
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
    """`ALWAYS_ON` can never appear here, because it is registered no matter what the selection is.
    This lets the tools that send a model to it continue to name it in every deployment."""
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
    """This matches a whole word, not a substring. `teams_read_message` is not mentioned by prose
    that says `read_messages`. Tool names use only `[a-z_]` characters, so a word boundary matches
    how a person reads the name."""
    return re.search(rf"\b{re.escape(name)}\b", prose) is not None


def _prose_of(tool: Tool) -> str:
    """An argument's description is where a tool names the tool that mints its handle. A scan of
    the tool description alone misses the references that matter most."""
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
