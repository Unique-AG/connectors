"""Which tools a deployment runs, and therefore what every one of its users consents to.

The one thing a restart cannot fix. Scopes ride `additional_authorize_scopes`, so a permission not
requested at sign-in cannot be redeemed by a later call — the On-Behalf-Of exchange fails with
AADSTS65001 before the tool body runs — and a permission requested that the app registration does
not carry fails the authorize hop for *every* user, with nothing in this server's logs. A selection
that is quietly one tool short is therefore a deployment nobody can correct from the outside, which
is why every way of writing one wrongly has to abort startup instead.

Two halves, each tested where it lives. `SurfaceConfig` decides whether the two environment
variables say anything usable at all — neither set, both set, an empty list, a preset that is not a
preset — because that is a question about the environment, and config is the only thing that reads
it. `resolve` decides what a usable answer expands to, and it is the only place that knows which
tools exist, so it is the only place that can call a tool name a typo.

Several tests here stand a registry of their own up in place of the real one. That is not a way
round the real thing: there is one tool in the tree and it is always on, so every selection resolves
to the same list, and the properties that matter most — that registry order beats the operator's
order, that a name not asked for is genuinely left out — would have nothing to bite on for another
nine pull requests. The stubs are the three things the registry reads off a tool module, and
nothing else.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import final

import httpx
import pytest
from fastmcp import FastMCP
from pydantic import ValidationError

import office_mcp.tools as tools_module
from office_mcp.config import SurfaceConfig, ToolsPreset
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

    It records its own registrations rather than being handed somewhere to write them, so a test can
    ask which modules were declared without anything holding a list on its behalf.
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

    Everything `resolve` reads is patched together — the modules, the names derived from them, and
    the preset mapping — because leaving one of the three behind would make a passing test prove
    nothing about the code the real registry runs.
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
        """Read out of the environment rather than handed in, because that is where the trap is: a
        collection-typed setting is JSON-decoded by the settings source before any validator of ours
        runs, so without `NoDecode` this exact value aborts startup with a JSON error and the remedy
        reads like a bug in this service. Blanks and a trailing comma are absorbed with it.
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
        """Caught by the enum, which is the whole reason the names live in config: the message lists
        the values that would have worked, and the same names fill the Helm chart's schema."""
        with pytest.raises(ValidationError) as refusal:
            SurfaceConfig.model_validate({"tools_preset": "teams-transcript"})

        assert ToolsPreset.TEAMS in str(refusal.value)


class TestConfigAndTheRegistryAgreeAboutPresetNames:
    """The names live in `config.py` and their contents in `tools/__init__.py`, so the two have to
    agree — and nothing but this makes them.

    Both directions, because each is a different failure. A `ToolsPreset` member with no mapping is
    a value pydantic accepts and `resolve` then cannot expand: a startup crash for a spelling this
    service's own error message recommended. A mapping with no member is a surface nobody can ask
    for, which is dead weight that reads as supported.
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

    def test_each_one_resolves_to_tools_this_server_actually_has(self) -> None:
        """The check the two above cannot make: they compare names, and a mapping is only as good as
        the tools it names."""
        for preset in ToolsPreset:
            selection = resolve(preset=preset, enabled=None)
            unknown = sorted(set(selection.tools) - set(TOOL_NAMES))

            assert selection.tools, f"{preset} resolves to no tools"
            assert not unknown, f"{preset} names tools this server does not have: {unknown}"


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
        """The consequence worth stating plainly: there is no such thing here as a consent screen
        that asks for nothing. `User.Read` is the least-privileged delegated permission Microsoft
        publishes and it needs no administrator."""
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
        """The whole point, and the thing FastMCP's `enable`/`disable` transforms cannot do: they
        hide a registered tool and leave the scopes already computed, so they shorten `tools/list`
        and change nothing whatever about what the tenant is asked to grant."""
        selection = resolve(preset=None, enabled=[_SECOND])
        mcp: FastMCP = FastMCP("selection-under-test", version="0")

        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)

        assert registry.registered() == [ALWAYS_ON, _SECOND]
        assert _OWN[1] not in selection.permissions
        assert graph_scope(_OWN[1]) not in selection.graph_scopes

    @pytest.mark.usefixtures("registry")
    def test_a_name_this_server_has_no_tool_for_aborts_and_lists_the_ones_it_has(self) -> None:
        """A typo must never quietly cost a tool: it would register one tool fewer and ask for one
        permission fewer than its operator believes, and the first sign of it is a model that cannot
        find a tool the deployment was supposed to expose — long after everyone consented."""
        with pytest.raises(ValueError, match="no tool for") as refusal:
            resolve(preset=None, enabled=[_SECOND, "secnod_tool"])

        assert "secnod_tool" in str(refusal.value)
        assert _SECOND in str(refusal.value)
        assert _THIRD in str(refusal.value)


class TestResolveTrustsConfigToHaveAskedTheQuestion:
    """The one-of rule is `SurfaceConfig`'s, so `resolve` asserts it rather than re-checking it —
    and the assertion is what says so out loud instead of a comment nobody reads."""

    def test_neither_argument_is_a_programming_error_here(self) -> None:
        with pytest.raises(AssertionError, match="exactly one"):
            resolve(preset=None, enabled=None)

    def test_and_so_are_both(self) -> None:
        with pytest.raises(AssertionError, match="exactly one"):
            resolve(preset=ToolsPreset.TEAMS, enabled=["get_me"])


class TestRegisteringWhatWasSelected:
    async def test_the_real_registry_declares_exactly_the_selection(self) -> None:
        """Against the real registry and a real server: with one tool in the tree this says the
        always-on floor is registered, which is the claim every deployment here rests on."""
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)
        mcp: FastMCP = FastMCP("registration-under-test", version="0")

        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)
            listed = {tool.name for tool in await mcp.list_tools()}

        assert listed == set(selection.tools)
