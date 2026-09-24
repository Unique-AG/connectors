import re
import textwrap
from collections.abc import Mapping, Sequence
from typing import cast

from fastmcp import FastMCP
from fastmcp.tools import Tool

from office_365_mcp.tools import ALWAYS_ON, TOOL_NAMES, Selection

NEEDS_ADMIN_CONSENT: Mapping[str, bool] = {
    "User.Read": False,
    "Chat.Read": False,
    "Team.ReadBasic.All": False,
    "Channel.ReadBasic.All": False,
    "ChannelMessage.Read.All": True,
    "ChatMessage.Send": False,
    "ChannelMessage.Send": False,
    "OnlineMeetings.Read": False,
    "OnlineMeetingTranscript.Read.All": True,
    "OnlineMeetingRecording.Read.All": True,
    "Mail.Read": False,
    "People.Read": False,
    "MailboxSettings.Read": False,
    "Mail.ReadWrite": False,
    "Mail.Send": False,
    "Mail.ReadBasic": False,
    "MailboxSettings.ReadWrite": False,
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
    return re.search(rf"\b{re.escape(name)}\b", prose) is not None


def _prose_of(tool: Tool) -> str:
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
