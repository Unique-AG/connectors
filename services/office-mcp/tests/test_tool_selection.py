"""Which tools a deployment runs, and therefore what every one of its users consents to.

The one thing a restart cannot fix. Scopes ride `additional_authorize_scopes`, so a permission not
requested at sign-in cannot be redeemed by a later call: the On-Behalf-Of exchange fails with
AADSTS65001 before the tool body runs. A permission requested that the app registration does not
carry fails the authorize hop for *every* user, with nothing in this server's logs. A selection
quietly one tool short is a deployment nobody can correct from the outside, so every way of writing
one wrongly has to abort startup instead.

Two halves, each tested where it lives. `SurfaceConfig` decides whether the two environment
variables say anything usable at all: neither set, both set, an empty list, or a preset that is not
a preset. That is a question about the environment, and config is the only thing that reads it.
`resolve` decides what a usable answer expands to, and it is the only place that knows which tools
exist, so it is the only place that can call a tool name a typo.

Several tests stand a registry of their own up in place of the real one, so that registry order
beating the operator's order, and a name not asked for being left out, are asserted against a fixed
list. The stubs are the three things the registry reads off a tool module, and nothing else.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import cast, final

import httpx
import pytest
from fastmcp import FastMCP
from pydantic import ValidationError

import office_mcp.tools as tools_module
from office_mcp.config import SurfaceConfig, ToolsPreset
from office_mcp.server.manifest import NEEDS_ADMIN_CONSENT
from office_mcp.shared.seam import graph_scope
from office_mcp.tools import ALWAYS_ON, PRESETS, TOOL_NAMES, register_tools, resolve

# One permission the two stub tools share and one each holds alone, so deduplication and order are
# both visible in the result rather than inferred from it.
_SHARED = "Chat.Read"
_OWN = ("Team.ReadBasic.All", "Channel.ReadBasic.All")

_SECOND = "second_tool"
_THIRD = "third_tool"


@final
@dataclass
class _StubModule:
    """A tool module in the only three respects the registry reads one.

    It records its own registrations, so a test can ask which modules were declared without
    anything holding a list on its behalf.
    """

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
    """The registry replaced by three tools, the always-on one first as the real registry has it.

    Everything `resolve` reads is patched together: the modules, the names derived from them, and
    the preset mapping. Leaving one of the three behind would make a passing test prove nothing
    about the code the real registry runs.
    """
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
    """`SurfaceConfig`: every way the environment fails to name a surface a deployment can run."""

    def test_a_preset_alone_is_a_selection(self) -> None:
        config = SurfaceConfig.model_validate({"tools_preset": ToolsPreset.TEAMS})

        assert config.tools_preset == ToolsPreset.TEAMS
        assert config.tools_enabled is None

    def test_a_list_alone_is_a_selection(self) -> None:
        config = SurfaceConfig.model_validate({"tools_enabled": "get_me,list_chats"})

        assert config.tools_preset is None
        assert config.tools_enabled == ("get_me", "list_chats")

    def test_the_spelling_an_operator_writes_is_the_one_that_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Read out of the environment rather than handed in, because the settings source only
        runs there: a collection-typed setting is JSON-decoded before any validator of ours, and
        the spelling every operator writes has to survive that. Blanks and a trailing comma are
        absorbed with it.
        """
        monkeypatch.setenv("TOOLS_ENABLED", "get_me, list_chats ,read_message,")

        config = SurfaceConfig()

        assert config.tools_enabled == ("get_me", "list_chats", "read_message")

    def test_neither_set_is_refused_and_says_what_to_set(self) -> None:
        """There is no default anywhere, deliberately: a default of "every tool" would make the
        widest consent screen the thing an operator gets by not choosing."""
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate({})

        assert "TOOLS_PRESET" in str(refusal.value)
        assert "TOOLS_ENABLED" in str(refusal.value)
        assert ToolsPreset.TEAMS in str(refusal.value)

    def test_both_set_is_refused_and_names_which_to_remove(self) -> None:
        """An error rather than a precedence rule, because a precedence rule is one nobody would
        remember and the cost of misremembering it is the wrong consent screen."""
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate(
                {"tools_preset": ToolsPreset.TEAMS, "tools_enabled": "get_me"}
            )

        assert "both are set" in str(refusal.value)
        assert "remove one" in str(refusal.value)

    def test_a_list_that_names_nothing_is_refused_by_name(self) -> None:
        """Distinct from not setting it at all, and worth its own message: an operator who wrote
        `TOOLS_ENABLED=` did choose the variable, and being told to set one of the two would read as
        this service not seeing what they set."""
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate({"tools_enabled": " , "})

        assert "names no tool" in str(refusal.value)

    def test_a_preset_that_is_not_one_is_refused_with_the_ones_that_are(self) -> None:
        """Caught by the enum, which is why the names live in config: the message lists the values
        that would have worked, and the same names fill the Helm chart's schema."""
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate({"tools_preset": "teams-transcript"})

        assert ToolsPreset.TEAMS in str(refusal.value)


class TestConfigAndTheRegistryAgreeAboutPresetNames:
    """The names live in `config.py` and their contents in `tools/__init__.py`, so the two have to
    agree, and nothing but this makes them.

    Both directions, because each fails differently. A `ToolsPreset` member with no mapping is a
    value pydantic accepts and `resolve` cannot expand: a startup crash for a spelling this
    service's own error message recommended. A mapping with no member is a surface nobody can ask
    for, dead weight that reads as supported.
    """

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
        """The check the two above cannot make: they compare names, and a mapping is only as good as
        the tools it names.

        The trap is asserting against what `resolve` returned. A selection's own `tools` are built
        by *filtering* the registry, so `resolve(...).tools - TOOL_NAMES` is empty whatever the
        mapping says, and a preset member one character wrong would resolve one tool short with a
        test like that still green. So this asserts against the registry. `teams` is derived from
        the registry and passes trivially. The hand-written presets are what this is for.
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
        """Guards the guard: the exception is hard-coded, so a rename would leave every selection
        one tool short of the only thing it is guaranteed."""
        assert ALWAYS_ON in TOOL_NAMES

    @pytest.mark.usefixtures("registry")
    def test_a_selection_that_does_not_name_it_gets_it_anyway(self) -> None:
        """Which lets `TOOLS_ENABLED` list only the rest, and lets a preset not mention it."""
        selection = resolve(preset=None, enabled=[_SECOND])

        assert selection.tools == (ALWAYS_ON, _SECOND)

    @pytest.mark.usefixtures("registry")
    def test_naming_it_explicitly_is_accepted_rather_than_an_error(self) -> None:
        """Because an operator who copies the manifest's tool list back into `TOOLS_ENABLED` will
        name it, and refusing that would punish the loop the manifest exists to close."""
        selection = resolve(preset=None, enabled=[ALWAYS_ON, _SECOND])

        assert selection.tools == (ALWAYS_ON, _SECOND)

    @pytest.mark.usefixtures("registry")
    def test_so_every_deployment_asks_for_at_least_one_permission(self) -> None:
        """No deployment here produces a consent screen that asks for nothing. `User.Read` is the
        least-privileged delegated permission Microsoft publishes and it needs no
        administrator."""
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
        """`dict.fromkeys` rather than a set: deduplicated, and in the order the registry reaches
        them, so the string does not move when a tool is added below."""
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
        """What FastMCP's `enable` and `disable` transforms cannot do: they hide a registered tool
        and leave the scopes already computed, so they shorten `tools/list` and change nothing about
        what the tenant is asked to grant."""
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
        """The runtime half of the guard above, and the reason it is an assertion rather than an
        exception: a preset that lists a tool this server does not have is a defect in the registry,
        not something an operator typed. Silence is the one answer it must not give: the tool would
        not register, and its permission would not be asked for.
        """
        monkeypatch.setattr(tools_module, "PRESETS", {ToolsPreset.TEAMS: (_SECOND, "secnod_tool")})

        with pytest.raises(AssertionError, match="no tool for") as refusal:
            resolve(preset=ToolsPreset.TEAMS, enabled=None)

        assert "secnod_tool" in str(refusal.value)

    @pytest.mark.usefixtures("registry")
    def test_a_name_this_server_has_no_tool_for_aborts_and_lists_the_ones_it_has(self) -> None:
        """A typo must never quietly cost a tool: it would register one tool fewer and ask for one
        permission fewer than its operator believes, and the first sign of it is a model that cannot
        find a tool the deployment was supposed to expose, long after everyone consented."""
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
        """The one test that compares what FastMCP lists against what the selection promised.

        `Selection.tools` is built from each module's `TOOL_NAME`, and what a model can call is the
        name that module passed to `@mcp.tool`. A tool registered under another spelling would
        still be selected and still have its permission asked for, and would never appear in
        `tools/list`. The stub registry hands FastMCP nothing, so no test over it can catch that.
        """
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)
        mcp: FastMCP = FastMCP("registration-under-test", version="0")

        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)
            listed = {tool.name for tool in await mcp.list_tools()}

        assert listed == set(selection.tools)


# Which tool mints the argument each consumer takes, written out rather than derived. Permissions do
# not encode it and nothing in `src/` guards it: a selection that enables a consumer without its
# producer starts, and the tool's own refusal names the missing tool on first use (F4 of the
# design). Catching it in `src/` would need a second declaration on every tool file, an enum of
# argument sources, a module in `shared/` and a validator: a large mechanism for a misconfiguration
# the operator caused explicitly. The presets this service ships promise something narrower, one
# assertion each: every tool in one can get its arguments from another member of it.
_ARGUMENT_SOURCES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "list_channels": {"team_id": ("list_teams",)},
    "browse_channel": {
        "team_id": ("list_teams",),
        "channel_id": ("list_channels", "search_messages"),
    },
    "read_message": {"uri": ("search_messages", "browse_channel")},
    # An Entra object id, which `get_me` is one source of by that argument's own description. Always
    # satisfied, because `get_me` is the floor. Recorded anyway, so the guard below can insist that
    # an argument naming a tool is classified as minted rather than as the caller's to compose.
    "search_messages": {"mentions": ("get_me",)},
    "list_meeting_transcripts": {"meeting_uri": ("list_chats",)},
    "read_transcript": {"uri": ("list_meeting_transcripts",)},
    "list_meeting_recordings": {"meeting_uri": ("list_chats",)},
}


# Arguments a caller composes rather than receives: `search_messages` requires at least one search
# criterion, which its schema says with nine one-name `anyOf` branches. None is minted by a tool, so
# none needs a producer. Listing them makes that a decision rather than a blind spot. An argument
# named here has been looked at and found not to be a handle.
_COMPOSED_BY_THE_CALLER: frozenset[str] = frozenset(
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
)


def _required_arguments(schema: Mapping[str, object]) -> set[str]:
    """Every argument a tool's schema requires, wherever the schema says so.

    Not just the top-level `required`: a tool that requires "at least one of these" says it with a
    `required` inside each branch of an `anyOf`, and reading only the top level would report
    `search_messages` as requiring nothing at all. So the whole schema is walked, and the
    classifying is done above rather than by where JSON Schema put the word.
    """
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
    """The tools `argument`'s own description names, other than the tool it belongs to."""
    properties = schema.get("properties", {})
    assert isinstance(properties, Mapping), f"expected properties, got {properties!r}"
    field = cast("Mapping[str, object]", properties).get(argument, {})
    description = str(cast("Mapping[str, object]", field).get("description", ""))
    return [name for name in TOOL_NAMES if name != besides and name in description]


class TestEveryCuratedPresetIsUsableOnItsOwn:
    """A preset is a use case, so every tool in one has to be reachable inside it.

    The failure this catches can have **no permission signature at all**. `teams-messages` without
    `search_messages` asks for the identical three permissions, `User.Read`, `Chat.Read` and
    `ChannelMessage.Read.All`, because `read_message` declares the last two itself. It also exposes
    a `read_message` nothing in the preset can address, because the handle it takes is minted by a
    tool that is not there. Nothing about the consent screen would look wrong.

    Written per preset against a table of argument sources, the trade the design records (F4): the
    presets this service ships are hand-written sets, so each is one assertion rather than a
    mechanism in the registry. A hand-written `TOOLS_ENABLED` may still name a consumer without its
    producer, and the tool's own refusal names the missing tool on first use.
    """

    def test_the_table_is_about_tools_this_server_has(self) -> None:
        """Guards the guard: a stale name on either side would quietly stop the check below from
        checking anything."""
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
        """And guards it from the side that actually goes stale: the arguments, read off the live
        schemas rather than off the table.

        A tool arriving with a required argument nobody classified would leave the check below
        passing while saying nothing about that argument. That is how the table came to record only
        one of `browse_channel`'s two required ids. Every required argument has to be one of two
        things: minted by another tool, or composed by the caller. Nothing may be neither.
        """
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)
        mcp: FastMCP = FastMCP("argument-survey", version="0")
        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)
            required = {
                tool.name: _required_arguments(tool.parameters) for tool in await mcp.list_tools()
            }

        unclassified = {
            name: sorted(arguments - set(_ARGUMENT_SOURCES.get(name, {})) - _COMPOSED_BY_THE_CALLER)
            for name, arguments in required.items()
            if arguments - set(_ARGUMENT_SOURCES.get(name, {})) - _COMPOSED_BY_THE_CALLER
        }

        assert not unclassified, (
            "every required argument is either minted by a tool — record which, in "
            + "_ARGUMENT_SOURCES — or composed by the caller, in _COMPOSED_BY_THE_CALLER. These "
            + f"are neither, so the check below says nothing about them: {unclassified}"
        )

    async def test_an_argument_whose_prose_names_a_tool_is_classified_as_minted(self) -> None:
        """The classification's own guard.

        `_COMPOSED_BY_THE_CALLER` is a flat list of names, so putting a handle in it would satisfy
        the completeness check above and quietly stop the reachability check below from asking about
        that tool at all. A minted argument names its producer in its own description, because that
        is how a model is told where to get one, so an argument whose prose names a tool must be
        recorded as minted.
        """
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)
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
        """The other half: an argument recorded in both places would be checked under whichever the
        code happened to consult first."""
        minted = {argument for arguments in _ARGUMENT_SOURCES.values() for argument in arguments}

        assert not minted & _COMPOSED_BY_THE_CALLER, (
            f"classified twice: {sorted(minted & _COMPOSED_BY_THE_CALLER)}"
        )

    @pytest.mark.parametrize("preset", list(ToolsPreset))
    def test_every_tool_in_it_can_obtain_its_arguments_from_another_member(
        self, preset: ToolsPreset
    ) -> None:
        """Every argument, not every tool: `browse_channel` takes a `team_id` and a `channel_id`
        from two different tools, so a preset holding one producer and not the other exposes a tool
        reachable for one of its arguments and not the other."""
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
        """A curated preset that quietly resolved to the whole surface would ask every tenant for
        every permission while reading as a narrow deployment: the exact thing this feature exists
        to stop, hidden behind a name that promises the opposite."""
        selection = resolve(preset=preset, enabled=None)

        if preset is ToolsPreset.TEAMS:
            assert set(selection.tools) == set(TOOL_NAMES)
        else:
            assert set(selection.tools) < set(TOOL_NAMES), f"{preset} is the whole surface"


# What each curated preset costs a tenant, transcribed from the design document's own table: the
# permissions it asks every user to consent to, how many of those need an administrator, and how
# many tools it exposes (counting the always-on floor). Written out rather than derived from
# `PRESETS`, because a derivation agrees with any mistake in `PRESETS`. Writing it out makes the
# promise these presets exist for, "one admin consent and no ChannelMessage.Read.All for a
# transcripts deployment", checkable rather than circular. The last test below states that row on
# its own.
_PRESET_COST: tuple[tuple[ToolsPreset, tuple[str, ...], int, int], ...] = (
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
)


class TestWhatEachPresetCostsATenant:
    """The consent screen each preset produces, which is the whole of what an operator is choosing.

    A preset whose tools drifted would still resolve, still register and still start. The only
    visible difference would be a permission on a consent screen a tenant already agreed to, and by
    then the deployment cannot be narrowed without every user signing in again.
    """

    def test_every_preset_has_a_cost_written_down(self) -> None:
        """Guards the guard: a preset added without a row here is a surface whose consent screen
        nothing checks."""
        priced = {preset for preset, _permissions, _consents, _tools in _PRESET_COST}

        assert priced == set(ToolsPreset), (
            f"no cost recorded for {sorted(set(ToolsPreset) - priced)}"
        )

    @pytest.mark.parametrize(("preset", "permissions", "consents", "tools"), _PRESET_COST)
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
        """The claim the design is built on: reading meeting transcripts costs one admin consent
        and does not drag in the permission to read every channel message in the tenant."""
        selection = resolve(preset=ToolsPreset.TEAMS_TRANSCRIPTS, enabled=None)

        assert "ChannelMessage.Read.All" not in selection.permissions
        assert graph_scope("ChannelMessage.Read.All") not in selection.graph_scopes
