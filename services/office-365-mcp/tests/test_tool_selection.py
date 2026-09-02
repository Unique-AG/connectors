"""Which tools a deployment runs, and therefore what every one of its users consents to.

The one thing a restart cannot fix. Scopes ride `additional_authorize_scopes`, so a permission not
requested at sign-in cannot be redeemed by a later call: the On-Behalf-Of exchange fails with
AADSTS65001 before the tool body runs. A permission the app registration does not carry fails the
authorize hop for *every* user, with nothing in this server's logs. So every way of writing a
selection wrongly has to abort startup instead.
"""

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
    """All three things `resolve` reads are patched together: the modules, the names derived from
    them, and the preset mapping. Leaving one behind would make a passing test prove nothing."""
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
        """Read out of the environment rather than handed in: a collection-typed setting is
        JSON-decoded before any validator of ours."""
        monkeypatch.setenv("TOOLS_ENABLED", "get_me, teams_list_chats ,teams_read_message,")

        config = SurfaceConfig()

        assert config.tools_enabled == ("get_me", "teams_list_chats", "teams_read_message")

    def test_neither_set_is_refused_and_says_what_to_set(self) -> None:
        """There is no default anywhere: a default of "every tool" would make the widest consent
        screen the thing an operator gets by not choosing."""
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate({})

        assert "TOOLS_PRESET" in str(refusal.value)
        assert "TOOLS_ENABLED" in str(refusal.value)
        assert ToolsPreset.TEAMS in str(refusal.value)

    def test_both_set_is_refused_and_names_which_to_remove(self) -> None:
        """An error rather than a precedence rule: misremembering one costs a consent screen."""
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
        """The names live in config because the same ones fill the Helm chart's schema."""
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
        """The trap is asserting against what `resolve` returned: a selection's own `tools` are
        built by *filtering* the registry, so `resolve(...).tools - TOOL_NAMES` is empty whatever
        the mapping says. Hence the comparison against `TOOL_NAMES`.
        """
        for preset, members in PRESETS.items():
            unknown = sorted(set(members) - set(TOOL_NAMES))

            assert members, f"{preset} maps to no tools, so nobody can usefully ask for it"
            assert not unknown, (
                f"{preset} names {unknown}, which this server has no tool for — it would resolve "
                + "that many tools short, and ask for that many permissions fewer"
            )


class TestGetMeIsAlwaysOn:
    def test_the_floor_is_a_tool_the_registry_actually_has(self) -> None:
        """`ALWAYS_ON` is hard-coded, so a rename would leave every selection one tool short."""
        assert ALWAYS_ON in TOOL_NAMES

    @pytest.mark.usefixtures("registry")
    def test_a_selection_that_does_not_name_it_gets_it_anyway(self) -> None:
        selection = resolve(preset=None, enabled=[_SECOND])

        assert selection.tools == (ALWAYS_ON, _SECOND)

    @pytest.mark.usefixtures("registry")
    def test_naming_it_explicitly_is_accepted_rather_than_an_error(self) -> None:
        """An operator copying the manifest's tool list back into `TOOLS_ENABLED` will name it."""
        selection = resolve(preset=None, enabled=[ALWAYS_ON, _SECOND])

        assert selection.tools == (ALWAYS_ON, _SECOND)

    @pytest.mark.usefixtures("registry")
    def test_so_every_deployment_asks_for_at_least_one_permission(self) -> None:
        """`User.Read` is the least-privileged delegated permission Microsoft publishes and needs
        no administrator."""
        selection = resolve(preset=None, enabled=[_SECOND])

        assert selection.permissions[0] == "User.Read"
        assert selection.graph_scopes[0] == graph_scope("User.Read")


class TestTheOrderIsTheRegistrysAndNeverTheOperators:
    """The consent screen and every cached On-Behalf-Of token key are keyed by the scope list as a
    string, so the same selection written two ways has to produce the same string."""

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
        """`dict.fromkeys` rather than a set: order-preserving, so the scope string does not
        move."""
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
        """What FastMCP's `enable`/`disable` transforms cannot do: they hide a registered tool but
        leave the scopes computed, so they shorten `tools/list` and change nothing about what the
        tenant is asked to grant."""
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
        """An assertion rather than an exception: a preset naming a missing tool is a registry
        defect, not something an operator typed."""
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
    """The one-of rule is `SurfaceConfig`'s, so `resolve` asserts it rather than re-checking it."""

    def test_neither_argument_is_a_programming_error_here(self) -> None:
        with pytest.raises(AssertionError, match="exactly one"):
            resolve(preset=None, enabled=None)

    def test_and_so_are_both(self) -> None:
        with pytest.raises(AssertionError, match="exactly one"):
            resolve(preset=ToolsPreset.TEAMS, enabled=["get_me"])


class TestRegisteringWhatWasSelected:
    async def test_the_real_registry_declares_exactly_the_selection(self) -> None:
        """`Selection.tools` is built from each module's `TOOL_NAME`; what a model can call is the
        name that module passed to `@mcp.tool`. A tool registered under another spelling would
        still be selected and never appear in `tools/list`. The stub registry hands FastMCP
        nothing, so no test over it can catch that.
        """
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)
        mcp: FastMCP = FastMCP("registration-under-test", version="0")

        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)
            listed = {tool.name for tool in await mcp.list_tools()}

        assert listed == set(selection.tools)


# Which tool mints the argument each consumer takes. Permissions do not encode it and nothing in
# `src/` guards it (F4 of the design): a selection that enables a consumer without its producer
# starts, and the tool's own refusal names the missing tool on first use.
_ARGUMENT_SOURCES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "teams_list_channels": {"team_id": ("teams_list_my_teams",)},
    "teams_browse_channel": {
        "team_id": ("teams_list_my_teams",),
        "channel_id": ("teams_list_channels", "teams_search_messages"),
    },
    "teams_read_message": {"uri": ("teams_search_messages", "teams_browse_channel")},
    # Always satisfied, `get_me` being the floor; recorded so the guard below sees it as minted.
    "teams_search_messages": {"mentions": ("get_me",)},
    "teams_list_meeting_transcripts": {"meeting_uri": ("teams_list_chats",)},
    "teams_read_transcript": {"uri": ("teams_list_meeting_transcripts",)},
    "teams_list_meeting_recordings": {"meeting_uri": ("teams_list_chats",)},
    "outlook_read_mail": {"uri": ("outlook_search_mail",)},
    "outlook_browse_folders": {"parent": ("outlook_browse_folders",)},
    "outlook_read_thread": {"uri": ("outlook_search_mail",)},
    "outlook_list_mail": {"folder_ref": ("outlook_browse_folders",)},
    "outlook_search_mail": {"recipient": ("get_me",)},
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
}


# Arguments a caller writes rather than copies from another tool's answer, per tool.
#
# TRAP: keyed by tool, not a flat set of names, because one name can be both. `recipient` is free
# text on `teams_search_messages` and is the signed-in user's own address on `outlook_search_mail`,
# whose description says to take it from `get_me` — under a flat set the second would inherit the
# first's classification and the reachability check below would never ask about it.
_COMPOSED_BY_THE_CALLER: Mapping[str, frozenset[str]] = {
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
    "outlook_search_mail": frozenset({"query", "sender", "subject"}),
    "outlook_list_mail": frozenset({"folder"}),
    "outlook_find_recipient": frozenset({"query"}),
    "outlook_mark_mail": frozenset({"is_read", "flagged", "importance"}),
    "outlook_move_mail": frozenset({"destination"}),
    "outlook_draft_mail": frozenset({"subject", "body_html"}),
    "outlook_draft_reply": frozenset({"mode", "body_html"}),
    "outlook_set_automatic_reply": frozenset({"status"}),
    "outlook_disable_mail_rule": frozenset({"enabled"}),
    "outlook_list_events": frozenset(
        {"starts_on", "ends_on", "time_zone", "with_person", "subject_contains"}
    ),
    "outlook_read_event": frozenset({"time_zone"}),
    "outlook_create_event": frozenset(
        {"subject", "starts_at", "ends_at", "time_zone", "attendees"}
    ),
}


def _required_arguments(schema: Mapping[str, object]) -> set[str]:
    """Not just the top-level `required`: a tool that requires "at least one of these" says it with
    a `required` inside each branch of an `anyOf`, and reading only the top level would report
    `teams_search_messages` as requiring nothing at all."""
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
    """The failure this catches can have **no permission signature at all**. `teams-messages`
    without `teams_search_messages` asks for the identical three permissions, because
    `teams_read_message`
    declares `Chat.Read` and `ChannelMessage.Read.All` itself — while exposing a
    `teams_read_message`
    nothing in the preset can address. A table rather than a mechanism in the registry is the trade
    the design records (F4).
    """

    def test_the_table_is_about_tools_this_server_has(self) -> None:
        """A stale name on either side stops the check below from checking anything."""
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
        """Read off the live schemas, which is the side that goes stale: that is how the table came
        to record only one of `teams_browse_channel`'s two required ids.
        """
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
        """`_COMPOSED_BY_THE_CALLER` is a flat list of names, so putting a handle in it would
        satisfy the completeness check above and quietly stop the reachability check below from
        asking about that tool at all.
        """
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
        """An argument in both places is checked under whichever the code consults first. Compared
        per tool, because the same name is legitimately minted for one tool and composed for
        another."""
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
        """Every argument, not every tool: `teams_browse_channel` takes its `team_id` and
        `channel_id`
        from two different tools, so a preset can hold one producer and not the other."""
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
        """A curated preset that resolved to the whole surface would ask every tenant for every
        permission while reading as a narrow deployment."""
        selection = resolve(preset=preset, enabled=None)

        if preset is ToolsPreset.TEAMS:
            assert set(selection.tools) <= set(TOOL_NAMES)
        else:
            assert set(selection.tools) < set(TOOL_NAMES), f"{preset} is the whole surface"

    def test_no_preset_is_derived_from_the_registry(self) -> None:
        """`teams` naming a tuple rather than `TOOL_NAMES` is the whole point: a derived preset
        takes in the first tool of another product and puts its permission on every `teams`
        tenant's consent screen."""
        derived = [name for name, tools in PRESETS.items() if tools is TOOL_NAMES]

        assert not derived, f"{derived} would grow with the registry rather than with a review"

    def test_every_registered_tool_is_reachable_through_some_preset(self) -> None:
        """The cost of writing `teams` out by hand: a tool can now land in the registry and be
        named by no preset at all, reachable only by `TOOLS_ENABLED`."""
        named = {tool for tools in PRESETS.values() for tool in tools} | {ALWAYS_ON}

        assert set(TOOL_NAMES) == named, f"no preset names {sorted(set(TOOL_NAMES) - named)}"


# Transcribed from the design document's own table: permissions consented to, how many need an
# administrator, how many tools (counting the always-on floor). Written out rather than derived
# from `PRESETS`, because a derivation agrees with any mistake in `PRESETS`.
#
# Public rather than private because `test_terraform_surface.py` prices the Terraform module's own
# copy of the registry against it: a second transcription there would be one more table to keep in
# step and no more witnesses than this one already is.
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
    (ToolsPreset.OUTLOOK_READ, ("User.Read", "Mail.Read", "People.Read"), 0, 7),
    (ToolsPreset.OUTLOOK_MAILBOX, ("User.Read", "MailboxSettings.Read"), 0, 2),
    (
        ToolsPreset.OUTLOOK_WRITE,
        ("User.Read", "Mail.Read", "People.Read", "Mail.ReadWrite"),
        0,
        11,
    ),
    (
        ToolsPreset.OUTLOOK_SEND,
        (
            "User.Read",
            "Mail.Read",
            "People.Read",
            "Mail.ReadWrite",
            "Mail.Send",
            "Mail.ReadBasic",
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
        ("User.Read", "Calendars.Read", "Calendars.Read.Shared"),
        0,
        4,
    ),
    (
        ToolsPreset.OUTLOOK_CALENDAR_WRITE,
        ("User.Read", "Calendars.Read", "Calendars.Read.Shared", "Calendars.ReadWrite"),
        0,
        5,
    ),
)


class TestWhatEachPresetCostsATenant:
    """A preset whose tools drifted would still resolve, register and start. The only visible
    difference is a permission on a consent screen the tenant already agreed to, and by then the
    deployment cannot be narrowed without every user signing in again.
    """

    def test_every_preset_has_a_cost_written_down(self) -> None:
        """A preset added without a row here is a surface whose consent screen nothing checks."""
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
