import ast
import re
from collections.abc import Callable, Mapping
from importlib import import_module
from pathlib import Path
from typing import cast

from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from mcp.types import Tool

from office_365_mcp.tools import TOOL_NAMES

_SURFACES = frozenset({"teams", "outlook", "sharepoint", "onenote"})

_VERBS = frozenset(
    {
        "add",
        "append",
        "cancel",
        "check",
        "copy",
        "create",
        "delete",
        "disable",
        "draft",
        "forward",
        "invite",
        "list",
        "mark",
        "move",
        "react",
        "read",
        "remove",
        "rename",
        "respond",
        "search",
        "send",
        "set",
        "share",
        "suggest",
        "unshare",
        "update",
    }
)

_VERB_OUTSIDE_THE_SET = frozenset(
    {
        "get_me",
        "teams_get_channel_files_folder",
        "outlook_get_mail_tips",
        "outlook_get_mailbox_settings",
        "sharepoint_get_list",
        "onenote_get_operation",
        "teams_browse_channel",
        "outlook_browse_folders",
        "sharepoint_browse_folder",
        "outlook_find_recipient",
        "outlook_find_rooms",
        "onenote_find_notebook_from_url",
        "teams_edit_message",
        "onenote_edit_page",
        "onenote_preview_page",
        "sharepoint_resolve_url",
    }
)

_DESCRIPTION_WITHOUT_NOTES = frozenset(
    {
        "teams_list_my_teams",
        "teams_search_messages",
        "teams_read_message",
        "outlook_browse_folders",
        "outlook_find_recipient",
        "outlook_read_thread",
        "outlook_move_mail",
        "outlook_list_categories",
        "sharepoint_get_list",
        "onenote_list_recent_notebooks",
    }
)

_LIMIT_WITHOUT_MAXIMUM = frozenset(
    {
        "teams_list_my_teams",
        "teams_list_channels",
        "teams_list_meeting_transcripts",
        "teams_read_transcript",
        "teams_list_call_transcripts",
        "teams_read_call_transcript",
        "teams_list_meeting_recordings",
        "outlook_browse_folders",
        "outlook_find_recipient",
        "outlook_list_events",
        "outlook_list_event_instances",
        "outlook_list_group_events",
        "sharepoint_search_files",
        "sharepoint_browse_folder",
        "sharepoint_search_sites",
        "sharepoint_list_lists",
        "sharepoint_list_items",
    }
)

_NEVER_ASKS = frozenset(
    {
        "outlook_create_category",
        "outlook_create_contact",
        "outlook_set_focused_override",
        "outlook_disable_mail_rule",
        "outlook_update_contact",
    }
)

_RETRIES_ITS_REPEATABLE_WRITE = frozenset[str]()

_ONE_LEAD_THEN_NOTES = re.compile(r"[^\n]+(?:\n[^\n]+)*\n\nNotes:\n(?:- [^\n]+(?:\n  [^\n]+)*\n?)+")


def _named(tools: list[Tool]) -> dict[str, Tool]:
    return {tool.name: tool for tool in tools}


def _verb(name: str) -> str:
    surface, verb, *_ = [*name.split("_"), ""]
    return verb if surface in _SURFACES else surface


def _module_tree(name: str) -> ast.Module:
    source = Path(cast("str", import_module(f"office_365_mcp.tools.{name}").__file__))
    return ast.parse(source.read_text(), filename=str(source))


def _called(node: ast.Call) -> str | None:
    match node.func:
        case ast.Name(id=called) | ast.Attribute(attr=called):
            return called
        case _:
            return None


def _calls(tree: ast.Module, predicate: Callable[[ast.Call], bool]) -> bool:
    return any(isinstance(node, ast.Call) and predicate(node) for node in ast.walk(tree))


def _asks_a_person(call: ast.Call) -> bool:
    return _called(call) == "person_confirms"


def _sends_without_retry(call: ast.Call) -> bool:
    return _called(call) == "no_retry" or any(
        keyword.arg == "safe_to_repeat"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False
        for keyword in call.keywords
    )


def _limit_bounds(tool: Tool) -> Mapping[str, object] | None:
    properties = cast("Mapping[str, object]", tool.input_schema.get("properties", {}))
    limit = properties.get("limit")
    return cast("Mapping[str, object]", limit) if isinstance(limit, dict) else None


def _breaks(violators: set[str], allowed: frozenset[str], rule: str) -> str:
    return (
        f"{rule}. New violations: {sorted(violators - allowed)}. Allowlisted but no longer "
        + f"violating, so drop them from the allowlist: {sorted(allowed - violators)}"
    )


class TestEveryToolFollowsOneTemplate:
    async def test_the_survey_covers_every_tool(self, every_tool: Client[FastMCPTransport]) -> None:
        assert set(_named(await every_tool.list_tools())) == set(TOOL_NAMES)

    async def test_a_tool_name_starts_with_a_verb_from_the_closed_set(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        violators = {
            tool.name for tool in await every_tool.list_tools() if _verb(tool.name) not in _VERBS
        }

        assert violators == _VERB_OUTSIDE_THE_SET, _breaks(
            violators, _VERB_OUTSIDE_THE_SET, f"a tool name starts with one of {sorted(_VERBS)}"
        )

    async def test_a_description_is_one_lead_paragraph_then_a_notes_block(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        violators = {
            tool.name
            for tool in await every_tool.list_tools()
            if not _ONE_LEAD_THEN_NOTES.fullmatch(tool.description or "")
        }

        assert violators == _DESCRIPTION_WITHOUT_NOTES, _breaks(
            violators,
            _DESCRIPTION_WITHOUT_NOTES,
            "a description is one lead paragraph, a blank line, `Notes:`, and `- ` bullets",
        )

    async def test_a_limit_publishes_its_minimum_and_maximum(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        limits = {
            tool.name: bounds
            for tool in await every_tool.list_tools()
            if (bounds := _limit_bounds(tool)) is not None
        }
        violators = {
            name
            for name, bounds in limits.items()
            if "minimum" not in bounds or "maximum" not in bounds
        }

        assert len(limits) > len(_LIMIT_WITHOUT_MAXIMUM), "the survey found too few limits"
        assert violators == _LIMIT_WITHOUT_MAXIMUM, _breaks(
            violators, _LIMIT_WITHOUT_MAXIMUM, "a `limit` parameter has `minimum` and `maximum`"
        )

    async def test_a_write_tool_asks_a_person_before_it_writes(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        """The check finds a call to `person_confirms` anywhere in the tool module, a local
        `a_person_agrees` wrapper included. It does not prove that the write waits for it."""
        writes = {
            tool.name
            for tool in await every_tool.list_tools()
            if tool.annotations is not None and tool.annotations.read_only_hint is False
        }
        violators = {name for name in writes if not _calls(_module_tree(name), _asks_a_person)}

        assert len(writes) > len(_NEVER_ASKS), "the survey found too few write tools"
        assert violators == _NEVER_ASKS, _breaks(
            violators, _NEVER_ASKS, "a write tool calls `person_confirms`"
        )

    async def test_a_write_that_a_repeat_can_do_twice_is_sent_without_retry(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        """The check finds a `no_retry()` call or a `safe_to_repeat=False` argument anywhere in the
        tool module. It does not prove that the request it guards is the one that a repeat can do
        twice, and it does not look into a shared module that the tool calls."""
        repeatable = {
            tool.name
            for tool in await every_tool.list_tools()
            if tool.annotations is not None and tool.annotations.idempotent_hint is False
        }
        violators = {
            name for name in repeatable if not _calls(_module_tree(name), _sends_without_retry)
        }

        assert repeatable, "the survey found no write that a repeat can do twice"
        assert violators == _RETRIES_ITS_REPEATABLE_WRITE, _breaks(
            violators,
            _RETRIES_ITS_REPEATABLE_WRITE,
            "a tool with `idempotentHint: false` sends with `no_retry()` or `safe_to_repeat=False`",
        )
