"""This deployment prints what it resolved to. Read this before you act on the manifest.

**This server has no way to compare a request against the app registration.** The session token's
`scp` claim carries only `access_as_user`, because Azure leaves Graph scopes out of it. A scope the
registration does not grant fails at the *authorize* step. The failure looks like an unknown scope,
or like a real but unconsented admin-consent permission stuck at "Need admin approval". This server
logs nothing in either case.

The manifest prints **no consent URL**. `/.default` consents to whatever the registration grants,
not to what this deployment asks for. A scope-matched admin-consent URL needs a `redirect_uri` that
matches a registered one. The only Web redirect URI that office-365-mcp registers is FastMCP's
OAuth callback, and that callback treats a *successful* consent as an error.

The description scan only **warns**. Requiring every mention drags `teams_search_messages` into a
deployment that asked only for `teams_list_chats`, and with it `ChannelMessage.Read.All` and a need
for an administrator's signature.
"""

import re
import textwrap
from collections.abc import Mapping, Sequence
from typing import cast

from fastmcp import FastMCP
from fastmcp.tools import Tool

from office_365_mcp.tools import ALWAYS_ON, TOOL_NAMES, Selection

# This table is not derived from tool code, and it cannot be. Needing consent is Microsoft's rule
# about the permission. No tool file knows this rule.
#
# The `False` entries make the table checkable. One test asserts that it answers for every name in
# `REQUESTABLE_PERMISSIONS`. A set holding only the names that need consent cannot tell "no" from
# "nobody said".
#
# Unlike `REQUESTABLE_PERMISSIONS`, a permission can appear here before a tool declares it. Nothing
# here reaches an authorize request.
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
    # Microsoft's rule about the permission. It is not a promise about a tenant. A tenant that runs
    # a restricted user-consent policy still stops an unprivileged user at "Need admin approval".
    "Mail.Read": False,
    "Mail.Read.Shared": False,
    "People.Read": False,
    "MailboxSettings.Read": False,
    "Mail.ReadWrite": False,
    "Mail.ReadWrite.Shared": False,
    "Mail.Send": False,
    "Mail.Send.Shared": False,
    "Mail.ReadBasic": False,
    "MailboxSettings.ReadWrite": False,
    # Microsoft publishes AdminConsentRequired: No for every delegated Calendars permission. This
    # includes the two `.Shared` permissions and `ReadBasic`.
    "Calendars.Read": False,
    "Calendars.Read.Shared": False,
    "Calendars.ReadBasic": False,
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
    """This runs on demand, so the `/manifest` route and the startup log line always match."""
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
    """`ALWAYS_ON` never appears here. It is registered no matter what the selection is. This is why
    the tools that point a model to `ALWAYS_ON` can say so in every deployment."""
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
    """This matches a whole word, not a substring. Prose that says `read_messages` does not mention
    `teams_read_message`. Tool names use only `[a-z_]` characters, so a word boundary in the regex
    falls where a reader sees one."""
    return re.search(rf"\b{re.escape(name)}\b", prose) is not None


def _prose_of(tool: Tool) -> str:
    """An argument's description is often where a tool names the tool that mints its handle. A scan
    of the tool description alone misses these references."""
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
