from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import cast, final

import httpx
import pytest
from fastmcp import FastMCP
from pydantic import ValidationError

import office_365_mcp.tools as tools_module
from office_365_mcp.config import SurfaceConfig, ToolsPreset
from office_365_mcp.server.manifest import NEEDS_ADMIN_CONSENT
from office_365_mcp.shared.seam import graph_scope
from office_365_mcp.tools import ALWAYS_ON, PRESETS, TOOL_NAMES, register_tools, resolve

_SHARED = "Chat.Read"
_OWN = ("Team.ReadBasic.All", "Channel.ReadBasic.All")

_SECOND = "second_tool"
_THIRD = "third_tool"


@final
@dataclass
class _StubModule:
    TOOL_NAME: str
    GRAPH_PERMISSIONS: tuple[str, ...]
    registrations: list[str] = field(default_factory=list[str])

    def register(self, _mcp: FastMCP, _transport: httpx.AsyncClient) -> None:
        self.registrations.append(self.TOOL_NAME)


@final
@dataclass(frozen=True)
class _Registry:
    modules: tuple[_StubModule, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(module.TOOL_NAME for module in self.modules)

    def registered(self) -> list[str]:
        return [module.TOOL_NAME for module in self.modules if module.registrations]


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Registry]:
    stubs = _Registry(
        (
            _StubModule(ALWAYS_ON, ("User.Read",)),
            _StubModule(_SECOND, (_SHARED, _OWN[0])),
            _StubModule(_THIRD, (_SHARED, _OWN[1])),
        )
    )
    monkeypatch.setattr(tools_module, "_TOOL_MODULES", stubs.modules)
    monkeypatch.setattr(tools_module, "TOOL_NAMES", stubs.names)
    monkeypatch.setattr(tools_module, "PRESETS", {ToolsPreset.TEAMS: stubs.names})
    yield stubs


class TestTheTwoVariablesAreOneChoice:
    def test_a_preset_alone_is_a_selection(self) -> None:
        config = SurfaceConfig.model_validate({"tools_preset": ToolsPreset.TEAMS})

        assert config.tools_preset == ToolsPreset.TEAMS
        assert config.tools_enabled is None

    def test_a_list_alone_is_a_selection(self) -> None:
        config = SurfaceConfig.model_validate({"tools_enabled": "get_me,teams_list_chats"})

        assert config.tools_preset is None
        assert config.tools_enabled == ("get_me", "teams_list_chats")

    def test_the_spelling_an_operator_writes_is_the_one_that_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TOOLS_ENABLED", "get_me, teams_list_chats ,teams_read_message,")

        config = SurfaceConfig()

        assert config.tools_enabled == ("get_me", "teams_list_chats", "teams_read_message")

    def test_neither_set_is_refused_and_says_what_to_set(self) -> None:
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate({})

        assert "TOOLS_PRESET" in str(refusal.value)
        assert "TOOLS_ENABLED" in str(refusal.value)
        assert ToolsPreset.TEAMS in str(refusal.value)

    def test_both_set_is_refused_and_names_which_to_remove(self) -> None:
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate(
                {"tools_preset": ToolsPreset.TEAMS, "tools_enabled": "get_me"}
            )

        assert "both are set" in str(refusal.value)
        assert "remove one" in str(refusal.value)

    def test_a_list_that_names_nothing_is_refused_by_name(self) -> None:
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate({"tools_enabled": " , "})

        assert "names no tool" in str(refusal.value)

    def test_a_preset_that_is_not_one_is_refused_with_the_ones_that_are(self) -> None:
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate({"tools_preset": "teams-transcript"})

        assert ToolsPreset.TEAMS in str(refusal.value)


class TestConfigAndTheRegistryAgreeAboutPresetNames:
    def test_every_preset_name_expands_to_tools(self) -> None:
        missing = [preset for preset in ToolsPreset if preset not in PRESETS]

        assert not missing, (
            f"config.ToolsPreset offers {missing}, which tools/__init__.py maps to no tools — "
            + "pydantic accepts the value and startup then aborts on it"
        )

    def test_every_mapped_surface_is_one_an_operator_can_ask_for(self) -> None:
        unreachable = [preset for preset in PRESETS if preset not in set(ToolsPreset)]

        assert not unreachable, (
            f"tools/__init__.py maps {unreachable}, which config.ToolsPreset does not offer, so no "
            + "TOOLS_PRESET value reaches it"
        )

    def test_each_one_names_only_tools_this_server_actually_has(self) -> None:
        for preset, members in PRESETS.items():
            unknown = sorted(set(members) - set(TOOL_NAMES))

            assert members, f"{preset} maps to no tools, so nobody can usefully ask for it"
            assert not unknown, (
                f"{preset} names {unknown}, which this server has no tool for — it would resolve "
                + "that many tools short, and ask for that many permissions fewer"
            )


class TestGetMeIsAlwaysOn:
    def test_the_floor_is_a_tool_the_registry_actually_has(self) -> None:
        assert ALWAYS_ON in TOOL_NAMES

    @pytest.mark.usefixtures("registry")
    def test_a_selection_that_does_not_name_it_gets_it_anyway(self) -> None:
        selection = resolve(preset=None, enabled=[_SECOND])

        assert selection.tools == (ALWAYS_ON, _SECOND)

    @pytest.mark.usefixtures("registry")
    def test_naming_it_explicitly_is_accepted_rather_than_an_error(self) -> None:
        selection = resolve(preset=None, enabled=[ALWAYS_ON, _SECOND])

        assert selection.tools == (ALWAYS_ON, _SECOND)

    @pytest.mark.usefixtures("registry")
    def test_so_every_deployment_asks_for_at_least_one_permission(self) -> None:
        selection = resolve(preset=None, enabled=[_SECOND])

        assert selection.permissions[0] == "User.Read"
        assert selection.graph_scopes[0] == graph_scope("User.Read")


class TestTheOrderIsTheRegistrysAndNeverTheOperators:
    def test_reordering_the_list_changes_neither_the_tools_nor_the_scopes(
        self, registry: _Registry
    ) -> None:
        forwards = resolve(preset=None, enabled=[_SECOND, _THIRD])
        backwards = resolve(preset=None, enabled=[_THIRD, _SECOND])

        assert forwards.tools == backwards.tools == registry.names
        assert forwards.graph_scopes == backwards.graph_scopes

    @pytest.mark.usefixtures("registry")
    def test_a_permission_two_tools_share_is_asked_for_once_where_the_first_reaches_it(
        self,
    ) -> None:
        selection = resolve(preset=None, enabled=[_THIRD, _SECOND])

        assert selection.permissions == ("User.Read", _SHARED, _OWN[0], _OWN[1])

    @pytest.mark.usefixtures("registry")
    def test_the_scopes_are_those_permissions_spelled_as_scopes(self) -> None:
        selection = resolve(preset=None, enabled=[_SECOND, _THIRD])

        assert selection.graph_scopes == tuple(
            graph_scope(permission) for permission in selection.permissions
        )


class TestANarrowedSelectionAsksForLess:
    async def test_a_tool_left_out_takes_its_permission_with_it_and_is_not_registered(
        self, registry: _Registry
    ) -> None:
        selection = resolve(preset=None, enabled=[_SECOND])
        mcp: FastMCP = FastMCP("selection-under-test", version="0")

        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)

        assert registry.registered() == [ALWAYS_ON, _SECOND]
        assert _OWN[1] not in selection.permissions
        assert graph_scope(_OWN[1]) not in selection.graph_scopes

    @pytest.mark.usefixtures("registry")
    def test_a_preset_naming_a_tool_this_server_lacks_is_not_quietly_shortened(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tools_module, "PRESETS", {ToolsPreset.TEAMS: (_SECOND, "secnod_tool")})

        with pytest.raises(AssertionError, match="no tool for") as refusal:
            resolve(preset=ToolsPreset.TEAMS, enabled=None)

        assert "secnod_tool" in str(refusal.value)

    @pytest.mark.usefixtures("registry")
    def test_a_name_this_server_has_no_tool_for_aborts_and_lists_the_ones_it_has(self) -> None:
        with pytest.raises(ValueError, match="no tool for") as refusal:
            resolve(preset=None, enabled=[_SECOND, "secnod_tool"])

        assert "secnod_tool" in str(refusal.value)
        assert _SECOND in str(refusal.value)
        assert _THIRD in str(refusal.value)


class TestResolveTrustsConfigToHaveAskedTheQuestion:
    def test_neither_argument_is_a_programming_error_here(self) -> None:
        with pytest.raises(AssertionError, match="exactly one"):
            resolve(preset=None, enabled=None)

    def test_and_so_are_both(self) -> None:
        with pytest.raises(AssertionError, match="exactly one"):
            resolve(preset=ToolsPreset.TEAMS, enabled=["get_me"])


class TestRegisteringWhatWasSelected:
    async def test_the_real_registry_declares_exactly_the_selection(self) -> None:
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)
        mcp: FastMCP = FastMCP("registration-under-test", version="0")

        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)
            listed = {tool.name for tool in await mcp.list_tools()}

        assert listed == set(selection.tools)


_ARGUMENT_SOURCES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "teams_list_channels": {"team_id": ("teams_list_my_teams",)},
    "teams_browse_channel": {
        "team_id": ("teams_list_my_teams",),
        "channel_id": ("teams_list_channels", "teams_search_messages"),
    },
    "teams_read_message": {"uri": ("teams_search_messages", "teams_browse_channel")},
    "teams_send_chat_message": {"chat_id": ("teams_list_chats",)},
    "teams_send_channel_message": {
        "team_id": ("teams_list_my_teams",),
        "channel_id": ("teams_list_channels", "teams_search_messages"),
    },
    "teams_search_messages": {"mentions": ("get_me",)},
    "teams_list_meeting_transcripts": {"meeting_uri": ("teams_list_chats",)},
    "teams_read_transcript": {"uri": ("teams_list_meeting_transcripts",)},
    "teams_list_meeting_recordings": {"meeting_uri": ("teams_list_chats",)},
    "outlook_read_mail": {"uri": ("outlook_search_mail",)},
    "outlook_browse_folders": {"parent": ("outlook_browse_folders",)},
    "outlook_read_thread": {"uri": ("outlook_search_mail",)},
    "outlook_list_mail": {"folder_ref": ("outlook_browse_folders",)},
    "outlook_search_mail": {"to": ("get_me",)},
    "outlook_mark_mail": {
        "message_refs": ("outlook_search_mail", "outlook_list_mail", "outlook_read_thread")
    },
    "outlook_move_mail": {
        "message_refs": ("outlook_search_mail", "outlook_list_mail", "outlook_read_thread"),
        "folder_ref": ("outlook_browse_folders",),
    },
    "outlook_draft_mail": {"to": ("outlook_find_recipient",)},
    "outlook_draft_reply": {
        "message_ref": ("outlook_search_mail", "outlook_list_mail", "outlook_read_thread")
    },
    "outlook_send_draft": {"draft_ref": ("outlook_draft_mail", "outlook_draft_reply")},
    "outlook_disable_mail_rule": {"rule_ref": ("outlook_get_mailbox_settings",)},
    "outlook_list_events": {"calendar_ref": ("outlook_list_calendars",)},
    "outlook_read_event": {"uri": ("outlook_list_events",)},
    "outlook_create_event_on_behalf": {"calendar_ref": ("outlook_list_calendars",)},
    "outlook_update_event": {"uri": ("outlook_list_events", "outlook_read_event")},
    "outlook_cancel_event": {"uri": ("outlook_list_events", "outlook_read_event")},
    "outlook_respond_to_invite": {"uri": ("outlook_list_events", "outlook_read_event")},
    "sharepoint_read_file": {"file": ("sharepoint_search_files", "sharepoint_browse_folder")},
    "onenote_read_page": {"page": ("onenote_list_pages",)},
    "onenote_append_to_page": {"page": ("onenote_list_pages", "onenote_create_page")},
    "onenote_preview_page": {"page": ("onenote_list_pages", "onenote_create_page")},
    "onenote_read_resource": {"resource": ("onenote_read_page", "onenote_preview_page")},
    "onenote_find_notebook_from_url": {
        "web_url": ("onenote_list_notebooks", "onenote_list_recent_notebooks")
    },
    "onenote_list_sections": {
        "parent": (
            "onenote_list_notebooks",
            "onenote_find_notebook_from_url",
            "onenote_list_sections",
            "onenote_create_notebook",
            "onenote_create_section_group",
        )
    },
    "onenote_create_section": {
        "parent": (
            "onenote_list_notebooks",
            "onenote_find_notebook_from_url",
            "onenote_list_sections",
            "onenote_create_notebook",
            "onenote_create_section_group",
        )
    },
    "onenote_create_section_group": {
        "parent": (
            "onenote_list_notebooks",
            "onenote_find_notebook_from_url",
            "onenote_list_sections",
            "onenote_create_notebook",
            "onenote_create_section_group",
        )
    },
    "onenote_edit_page": {"page": ("onenote_list_pages", "onenote_create_page")},
    "onenote_rename_page": {"page": ("onenote_list_pages", "onenote_create_page")},
    "onenote_delete_page": {"page": ("onenote_list_pages", "onenote_create_page")},
    "onenote_copy_page": {
        "page": ("onenote_list_pages", "onenote_create_page"),
        "to_section": ("onenote_list_notebooks", "onenote_list_sections", "onenote_create_section"),
    },
    "onenote_copy_section": {
        "section": ("onenote_list_notebooks", "onenote_list_sections", "onenote_create_section"),
        "to_notebook": (
            "onenote_list_notebooks",
            "onenote_find_notebook_from_url",
            "onenote_create_notebook",
        ),
        "to_section_group": ("onenote_list_sections", "onenote_create_section_group"),
    },
    "onenote_copy_notebook": {
        "notebook": (
            "onenote_list_notebooks",
            "onenote_find_notebook_from_url",
            "onenote_create_notebook",
        )
    },
    "onenote_get_operation": {
        "operation": ("onenote_copy_page", "onenote_copy_section", "onenote_copy_notebook")
    },
}


_COMPOSED_BY_THE_CALLER: Mapping[str, frozenset[str]] = {
    "teams_send_chat_message": frozenset({"message"}),
    "teams_send_channel_message": frozenset({"message"}),
    "teams_search_messages": frozenset(
        {
            "query",
            "sender",
            "recipient",
            "sent_after",
            "sent_before",
            "has_attachment",
            "is_read",
            "mentions_me",
        }
    ),
    "outlook_search_mail": frozenset(
        {"query", "sender", "recipient", "subject", "attachment_name"}
    ),
    "outlook_list_mail": frozenset({"folder"}),
    "outlook_find_recipient": frozenset({"query"}),
    "outlook_mark_mail": frozenset({"is_read", "flagged", "importance"}),
    "outlook_move_mail": frozenset({"destination"}),
    "outlook_draft_mail": frozenset({"subject", "body_html"}),
    "outlook_draft_reply": frozenset({"mode", "body_html"}),
    "outlook_set_automatic_reply": frozenset({"status"}),
    "outlook_disable_mail_rule": frozenset({"enabled"}),
    "outlook_list_events": frozenset({"starts_on", "ends_on", "time_zone", "subject_contains"}),
    "outlook_read_event": frozenset({"time_zone"}),
    "outlook_create_event": frozenset(
        {"subject", "starts_at", "ends_at", "time_zone", "attendees"}
    ),
    "outlook_create_event_on_behalf": frozenset(
        {"subject", "starts_at", "ends_at", "time_zone", "attendees"}
    ),
    "outlook_respond_to_invite": frozenset({"response"}),
    "outlook_check_availability": frozenset({"addresses", "starts_at", "ends_at", "time_zone"}),
    "outlook_suggest_meeting_times": frozenset({"attendees", "starts_at", "ends_at", "time_zone"}),
    "sharepoint_search_files": frozenset({"query"}),
    "onenote_list_pages": frozenset({"title_contains"}),
    "onenote_create_page": frozenset({"title", "body_html"}),
    "onenote_append_to_page": frozenset({"body_html"}),
    "onenote_create_notebook": frozenset({"name"}),
    "onenote_create_section": frozenset({"name"}),
    "onenote_create_section_group": frozenset({"name"}),
    "onenote_edit_page": frozenset({"commands", "target", "action", "content"}),
    "onenote_rename_page": frozenset({"title"}),
}


def _required_arguments(schema: Mapping[str, object]) -> set[str]:
    found: set[str] = set()
    pending: list[object] = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, Mapping):
            for key, value in cast("Mapping[str, object]", node).items():
                if key == "required" and isinstance(value, list):
                    found |= {name for name in cast("list[object]", value) if isinstance(name, str)}
                else:
                    pending.append(value)
        elif isinstance(node, list):
            pending.extend(cast("list[object]", node))
    return found


def _tools_named_by(schema: Mapping[str, object], argument: str, *, besides: str) -> list[str]:
    properties = schema.get("properties", {})
    assert isinstance(properties, Mapping), f"expected properties, got {properties!r}"
    field = cast("Mapping[str, object]", properties).get(argument, {})
    description = str(cast("Mapping[str, object]", field).get("description", ""))
    return [name for name in TOOL_NAMES if name != besides and name in description]


class TestEveryCuratedPresetIsUsableOnItsOwn:
    def test_the_table_is_about_tools_this_server_has(self) -> None:
        named = {*_ARGUMENT_SOURCES} | {
            producer
            for arguments in _ARGUMENT_SOURCES.values()
            for producers in arguments.values()
            for producer in producers
        }

        assert not named - set(TOOL_NAMES), (
            f"unknown tools in the table: {sorted(named - set(TOOL_NAMES))}"
        )

    async def test_the_table_answers_for_every_argument_a_tool_requires(self) -> None:
        selection = resolve(preset=None, enabled=list(TOOL_NAMES))
        mcp: FastMCP = FastMCP("argument-survey", version="0")
        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)
            required = {
                tool.name: _required_arguments(tool.parameters) for tool in await mcp.list_tools()
            }

        unclassified = {
            name: sorted(
                arguments
                - set(_ARGUMENT_SOURCES.get(name, {}))
                - _COMPOSED_BY_THE_CALLER.get(name, frozenset())
            )
            for name, arguments in required.items()
            if arguments
            - set(_ARGUMENT_SOURCES.get(name, {}))
            - _COMPOSED_BY_THE_CALLER.get(name, frozenset())
        }

        assert not unclassified, (
            "every required argument is either minted by a tool — record which, in "
            + "_ARGUMENT_SOURCES — or composed by the caller, in _COMPOSED_BY_THE_CALLER. These "
            + f"are neither, so the check below says nothing about them: {unclassified}"
        )

    async def test_an_argument_whose_prose_names_a_tool_is_classified_as_minted(self) -> None:
        selection = resolve(preset=None, enabled=list(TOOL_NAMES))
        mcp: FastMCP = FastMCP("prose-survey", version="0")
        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)
            listed = await mcp.list_tools()

        misclassified = {
            f"{tool.name}.{argument}": named
            for tool in listed
            for argument in _required_arguments(tool.parameters)
            if argument not in _ARGUMENT_SOURCES.get(tool.name, {})
            for named in [_tools_named_by(tool.parameters, argument, besides=tool.name)]
            if named
        }

        assert not misclassified, (
            "these arguments say in their own description which tool mints them, so they belong in "
            + f"_ARGUMENT_SOURCES and not in _COMPOSED_BY_THE_CALLER: {misclassified}"
        )

    def test_nothing_is_both_minted_and_composed(self) -> None:
        twice = {
            f"{tool}.{argument}"
            for tool, minted in _ARGUMENT_SOURCES.items()
            for argument in set(minted) & _COMPOSED_BY_THE_CALLER.get(tool, frozenset())
        }

        assert not twice, f"classified twice: {sorted(twice)}"

    @pytest.mark.parametrize("preset", list(ToolsPreset))
    def test_every_tool_in_it_can_obtain_its_arguments_from_another_member(
        self, preset: ToolsPreset
    ) -> None:
        selection = resolve(preset=preset, enabled=None)
        exposed = set(selection.tools)

        unreachable = {
            f"{tool}.{argument}": producers
            for tool in selection.tools
            for argument, producers in _ARGUMENT_SOURCES.get(tool, {}).items()
            if not set(producers) & exposed
        }

        assert not unreachable, f"{preset} exposes arguments nothing in it can mint: " + ", ".join(
            f"{where} needs one of {producers}" for where, producers in unreachable.items()
        )

    @pytest.mark.parametrize("preset", list(ToolsPreset))
    def test_it_is_narrower_than_everything_or_is_everything(self, preset: ToolsPreset) -> None:
        selection = resolve(preset=preset, enabled=None)

        if preset is ToolsPreset.TEAMS:
            assert set(selection.tools) <= set(TOOL_NAMES)
        else:
            assert set(selection.tools) < set(TOOL_NAMES), f"{preset} is the whole surface"

    def test_no_preset_is_derived_from_the_registry(self) -> None:
        derived = [name for name, tools in PRESETS.items() if tools is TOOL_NAMES]

        assert not derived, f"{derived} would grow with the registry rather than with a review"

    def test_every_registered_tool_is_reachable_through_some_preset(self) -> None:
        named = {tool for tools in PRESETS.values() for tool in tools} | {ALWAYS_ON}

        assert set(TOOL_NAMES) == named, f"no preset names {sorted(set(TOOL_NAMES) - named)}"


PRESET_COST: tuple[tuple[ToolsPreset, tuple[str, ...], int, int], ...] = (
    (ToolsPreset.TEAMS_CHAT, ("User.Read", "Chat.Read"), 0, 2),
    (ToolsPreset.TEAMS_MESSAGES, ("User.Read", "Chat.Read", "ChannelMessage.Read.All"), 1, 4),
    (
        ToolsPreset.TEAMS_CHANNELS,
        ("User.Read", "Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Read.All"),
        1,
        4,
    ),
    (
        ToolsPreset.TEAMS_TRANSCRIPTS,
        ("User.Read", "Chat.Read", "OnlineMeetings.Read", "OnlineMeetingTranscript.Read.All"),
        1,
        4,
    ),
    (
        ToolsPreset.TEAMS_RECORDINGS,
        ("User.Read", "Chat.Read", "OnlineMeetings.Read", "OnlineMeetingRecording.Read.All"),
        1,
        3,
    ),
    (
        ToolsPreset.TEAMS_MEETINGS,
        (
            "User.Read",
            "Chat.Read",
            "OnlineMeetings.Read",
            "OnlineMeetingTranscript.Read.All",
            "OnlineMeetingRecording.Read.All",
        ),
        2,
        5,
    ),
    (
        ToolsPreset.TEAMS,
        (
            "User.Read",
            "Chat.Read",
            "Team.ReadBasic.All",
            "Channel.ReadBasic.All",
            "ChannelMessage.Read.All",
            "OnlineMeetings.Read",
            "OnlineMeetingTranscript.Read.All",
            "OnlineMeetingRecording.Read.All",
        ),
        3,
        10,
    ),
    (
        ToolsPreset.TEAMS_WRITE,
        (
            "User.Read",
            "Chat.Read",
            "Team.ReadBasic.All",
            "Channel.ReadBasic.All",
            "ChatMessage.Send",
            "ChannelMessage.Send",
        ),
        0,
        6,
    ),
    (
        ToolsPreset.OUTLOOK_READ,
        ("User.Read", "Mail.Read", "Mail.Read.Shared", "People.Read"),
        0,
        7,
    ),
    (ToolsPreset.OUTLOOK_MAILBOX, ("User.Read", "MailboxSettings.Read"), 0, 3),
    (
        ToolsPreset.OUTLOOK_WRITE,
        (
            "User.Read",
            "Mail.Read",
            "Mail.Read.Shared",
            "People.Read",
            "Mail.ReadWrite",
            "Mail.ReadWrite.Shared",
        ),
        0,
        11,
    ),
    (
        ToolsPreset.OUTLOOK_SEND,
        (
            "User.Read",
            "Mail.Read",
            "Mail.Read.Shared",
            "People.Read",
            "Mail.ReadWrite",
            "Mail.ReadWrite.Shared",
            "Mail.Send",
            "Mail.ReadBasic",
            "Mail.Send.Shared",
        ),
        0,
        12,
    ),
    (
        ToolsPreset.OUTLOOK_AUTOMATE,
        ("User.Read", "MailboxSettings.Read", "MailboxSettings.ReadWrite"),
        0,
        4,
    ),
    (
        ToolsPreset.OUTLOOK_CALENDAR,
        ("User.Read", "Calendars.Read", "Calendars.Read.Shared", "Calendars.ReadBasic"),
        0,
        6,
    ),
    (
        ToolsPreset.OUTLOOK_CALENDAR_WRITE,
        (
            "User.Read",
            "Calendars.Read",
            "Calendars.Read.Shared",
            "Calendars.ReadBasic",
            "Calendars.ReadWrite",
        ),
        0,
        10,
    ),
    (
        ToolsPreset.OUTLOOK_CALENDAR_DELEGATE,
        (
            "User.Read",
            "Calendars.Read",
            "Calendars.Read.Shared",
            "Calendars.ReadBasic",
            "Calendars.ReadWrite",
            "Calendars.ReadWrite.Shared",
        ),
        0,
        11,
    ),
    (ToolsPreset.SHAREPOINT_SEARCH, ("User.Read", "Files.Read.All"), 1, 3),
    (ToolsPreset.SHAREPOINT_READ, ("User.Read", "Files.Read.All"), 1, 4),
    (ToolsPreset.ONENOTE_READ, ("User.Read", "Notes.Read"), 0, 9),
    (
        ToolsPreset.ONENOTE_WRITE,
        ("User.Read", "Notes.Read", "Notes.Create", "Notes.ReadWrite"),
        0,
        20,
    ),
    (
        ToolsPreset.ONENOTE_DELETE,
        ("User.Read", "Notes.Read", "Notes.Create", "Notes.ReadWrite"),
        0,
        21,
    ),
)


class TestWhatEachPresetCostsATenant:
    def test_every_preset_has_a_cost_written_down(self) -> None:
        priced = {preset for preset, _permissions, _consents, _tools in PRESET_COST}

        assert priced == set(ToolsPreset), (
            f"no cost recorded for {sorted(set(ToolsPreset) - priced)}"
        )

    @pytest.mark.parametrize(("preset", "permissions", "consents", "tools"), PRESET_COST)
    def test_it_asks_for_exactly_the_permissions_the_design_promises(
        self, preset: ToolsPreset, permissions: tuple[str, ...], consents: int, tools: int
    ) -> None:
        selection = resolve(preset=preset, enabled=None)
        needing_an_administrator = [
            permission for permission in selection.permissions if NEEDS_ADMIN_CONSENT[permission]
        ]

        assert set(selection.permissions) == set(permissions)
        assert len(selection.permissions) == len(permissions), "a permission is asked for twice"
        assert len(needing_an_administrator) == consents, (
            f"{preset} needs {needing_an_administrator}, and the design promises {consents}"
        )
        assert len(selection.tools) == tools

    def test_the_transcripts_deployment_does_not_pay_for_channel_messages(self) -> None:
        selection = resolve(preset=ToolsPreset.TEAMS_TRANSCRIPTS, enabled=None)

        assert "ChannelMessage.Read.All" not in selection.permissions
        assert graph_scope("ChannelMessage.Read.All") not in selection.graph_scopes
