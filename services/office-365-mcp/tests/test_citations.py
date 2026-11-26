from collections.abc import Mapping
from typing import cast

from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from mcp.types import Tool

from office_365_mcp.shared.citations import ACTION_NOT_A_SOURCE, lookup_not_a_source

# The keys Unique's chat (Conduct) reads a record's title and link from. `uri` is a link key there
# too, but every `uri` of this connector is a handle such as `teams:///...`, which it never cites.
_TITLE_KEYS = frozenset({"title", "name", "displayName", "display_name", "subject", "summary"})
_LINK_KEYS = frozenset({"url", "href", "webUrl", "web_url", "webLink", "web_link", "link"})

_SOURCES = frozenset(
    {
        "onenote_read_page",
        "outlook_list_event_instances",
        "outlook_list_events",
        "outlook_list_group_events",
        "outlook_list_mail",
        "outlook_list_reminders",
        "outlook_read_event",
        "outlook_read_mail",
        "outlook_read_thread",
        "outlook_search_mail",
        "sharepoint_list_items",
        "sharepoint_search_files",
        "teams_browse_channel",
        "teams_list_chat_messages",
        "teams_list_message_replies",
        "teams_read_message",
        "teams_search_messages",
    }
)

_LOOKUPS = frozenset(
    {
        "onenote_find_notebook_from_url",
        "onenote_list_notebooks",
        "onenote_list_pages",
        "onenote_list_recent_notebooks",
        "onenote_list_sections",
        "sharepoint_browse_folder",
        "sharepoint_list_drives",
        "sharepoint_list_lists",
        "sharepoint_resolve_url",
        "sharepoint_search_sites",
        "teams_get_channel_files_folder",
    }
)

_DO_NOT_CITE = "Do not cite this tool's result"


def _resolved(schema: object, definitions: Mapping[str, object]) -> Mapping[str, object]:
    node = cast("Mapping[str, object]", schema)
    if "$ref" in node:
        return _resolved(definitions[str(node["$ref"]).rsplit("/", 1)[-1]], definitions)
    variants = cast("list[object]", node.get("anyOf", []))
    for variant in variants:
        if cast("Mapping[str, object]", variant).get("type") != "null":
            return _resolved(variant, definitions)
    return node


def _properties(schema: Mapping[str, object]) -> Mapping[str, object]:
    return cast("Mapping[str, object]", schema.get("properties", {}))


def _linked_and_titled(record: Mapping[str, object]) -> bool:
    keys = set(_properties(record))
    links = {key for key in keys if key in _LINK_KEYS or key.endswith(("_url", "_link"))}
    return bool(keys & _TITLE_KEYS) and bool(links)


def _is_record(record: Mapping[str, object]) -> bool:
    return bool(set(_properties(record)) & (_TITLE_KEYS | _LINK_KEYS | {"uri"}))


def _cited(tool: Tool) -> bool:
    """Mirrors how Conduct reads a result: a record at the top, else the records of its lists."""
    schema = tool.output_schema or {}
    definitions = cast("Mapping[str, object]", schema.get("$defs", {}))
    top = _resolved(schema, definitions)
    if _is_record(top):
        return _linked_and_titled(top)
    lists = (_resolved(value, definitions) for value in _properties(top).values())
    return any(
        _linked_and_titled(_resolved(listed.get("items", {}), definitions))
        for listed in lists
        if listed.get("type") == "array"
    )


class TestWhatUniqueCites:
    async def test_every_titled_and_linked_result_is_a_source_or_says_not_to_cite_it(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        cited = {tool.name for tool in await every_tool.list_tools() if _cited(tool)}
        told_not_to = {
            tool.name
            for tool in await every_tool.list_tools()
            if _DO_NOT_CITE in (tool.description or "")
        }

        assert cited - told_not_to == _SOURCES
        assert told_not_to <= cited, "a result Unique never cites needs no note"

    async def test_a_lookup_names_what_to_cite_instead(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        tools = {tool.name: tool for tool in await every_tool.list_tools()}

        for name in _LOOKUPS:
            description = tools[name].description or ""
            assert "Do not cite this tool's results: they help you find " in description, name
            assert "they are not sources. Cite the " in description, name

    async def test_an_action_says_its_result_is_not_a_source(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        tools = await every_tool.list_tools()
        actions = {tool.name for tool in tools if ACTION_NOT_A_SOURCE in (tool.description or "")}

        assert actions == {tool.name for tool in tools if _cited(tool)} - _SOURCES - _LOOKUPS
        assert all(
            tool.annotations is not None and tool.annotations.read_only_hint is False
            for tool in tools
            if tool.name in actions
        ), "only a tool that changes something reports a change"

    def test_a_lookup_note_names_what_it_finds_and_what_to_cite(self) -> None:
        assert lookup_not_a_source("sites", cite="the file you read with sharepoint_read_file") == (
            "Do not cite this tool's results: they help you find sites, they are not sources. "
            + "Cite the file you read with sharepoint_read_file instead."
        )
