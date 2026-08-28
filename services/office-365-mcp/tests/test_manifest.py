"""What an operator is told this deployment resolved to.

Azure omits Graph scopes from the session token's `scp` and the grants are invisible here, so a
mismatch surfaces only at the *authorize* hop — a login no user can complete, with nothing in this
server's logs to explain it. The manifest is the only place the permission list exists.
"""

import re
from collections.abc import Iterator, Mapping

import httpx
import pytest
from fastmcp import FastMCP

import office_365_mcp.server.manifest as manifest_module
from office_365_mcp.config import ToolsPreset
from office_365_mcp.server import surface_manifest
from office_365_mcp.server.manifest import NEEDS_ADMIN_CONSENT
from office_365_mcp.shared.seam import REQUESTABLE_PERMISSIONS
from office_365_mcp.tools import ALWAYS_ON, Selection, register_tools, resolve

_VERSION = "9.9.9"

_SECOND = "second_tool"
_THIRD = "third_tool"


@pytest.fixture
def registry_of_three(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(manifest_module, "TOOL_NAMES", (ALWAYS_ON, _SECOND, _THIRD))
    yield


async def _manifest_of(selection: Selection, *, tools: Mapping[str, str] | None = None) -> str:
    """A real `FastMCP` and not a stub: the scan reads prose off the registered tools."""
    mcp: FastMCP = FastMCP("manifest-under-test", version=_VERSION)
    for name, description in (tools or {}).items():
        _carrying_prose(mcp, name, description)
    return await surface_manifest(mcp, selection, version=_VERSION)


def _flat(manifest: str) -> str:
    return " ".join(manifest.split())


def _carrying_prose(mcp: FastMCP, name: str, description: str) -> None:
    def _stub() -> str:
        return name

    mcp.tool(name=name, description=description)(_stub)


class TestTheTableAnswersForEveryPermissionAToolCanDeclare:
    """`NEEDS_ADMIN_CONSENT` is hand-written: needing consent is Microsoft's rule about a
    permission, and no tool file knows it."""

    def test_every_permission_this_connector_may_ask_for_has_a_verdict(self) -> None:
        unanswered = sorted(REQUESTABLE_PERMISSIONS - set(NEEDS_ADMIN_CONSENT))

        assert not unanswered, (
            f"{unanswered} can be declared by a tool and reach the consent screen, but "
            + "NEEDS_ADMIN_CONSENT does not say whether an administrator has to grant them. Add "
            + "each one with its verdict from Microsoft's permissions reference"
        )

    def test_it_answers_for_nothing_else(self) -> None:
        unrequestable = sorted(set(NEEDS_ADMIN_CONSENT) - REQUESTABLE_PERMISSIONS)

        assert not unrequestable, (
            f"NEEDS_ADMIN_CONSENT answers for {unrequestable}, which no tool may declare — either "
            + "the spelling is wrong, or the permission was removed and its verdict left behind"
        )

    def test_the_verdicts_are_not_all_the_same_answer(self) -> None:
        """An all-`False` table would pass the totality check above."""
        assert set(NEEDS_ADMIN_CONSENT.values()) == {True, False}


class TestWhatTheManifestSays:
    async def test_it_names_the_variable_that_produced_the_surface(self) -> None:
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        manifest = await _manifest_of(selection)

        assert f"TOOLS_PRESET={ToolsPreset.TEAMS}" in manifest

    async def test_a_hand_written_list_is_named_as_one(self) -> None:
        selection = resolve(preset=None, enabled=[ALWAYS_ON])

        manifest = await _manifest_of(selection)

        assert "TOOLS_ENABLED" in manifest
        assert "TOOLS_PRESET" not in manifest

    async def test_it_lists_the_resolved_tools_and_marks_the_one_nobody_asked_for(self) -> None:
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        manifest = await _manifest_of(selection)

        assert f"tools ({len(selection.tools)})" in manifest
        assert f"{ALWAYS_ON} (always on)" in manifest

    async def test_it_lists_the_permissions_in_entras_own_spelling(self) -> None:
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        manifest = await _manifest_of(selection)

        assert f"permissions ({len(selection.permissions)})" in manifest
        for permission in selection.permissions:
            assert permission in manifest
        assert "https://graph.microsoft.com/" not in manifest

    async def test_it_says_which_permissions_need_an_administrator(self) -> None:
        selection = Selection(
            preset=None,
            tools=(ALWAYS_ON,),
            permissions=("User.Read", "ChannelMessage.Read.All"),
            graph_scopes=(),
        )

        manifest = await _manifest_of(selection)

        assert re.search(r"admin consent\s+ChannelMessage\.Read\.All", manifest)

    async def test_it_says_so_when_none_of_them_do(self) -> None:
        selection = resolve(preset=None, enabled=[ALWAYS_ON])

        manifest = await _manifest_of(selection)

        assert re.search(r"admin consent\s+none", manifest)

    async def test_it_carries_no_consent_url(self) -> None:
        """`/.default` would consent to whatever the registration carries rather than to this
        deployment's ask, and a scope-matched admin-consent URL needs a registered `redirect_uri` —
        the only one here is FastMCP's OAuth callback, which renders a successful consent as an
        error."""
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        manifest = await _manifest_of(selection)

        assert "adminconsent" not in manifest
        assert "login.microsoftonline.com" not in manifest
        assert "https://" not in manifest

    async def test_it_carries_the_version_that_resolved_it(self) -> None:
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        manifest = await _manifest_of(selection)

        assert manifest.startswith(f"office-365-mcp {_VERSION} —")


class TestTheDescriptionScanWarnsAboutStalePromises:
    """It warns and never aborts: the references are dense and mutual, so requiring every mention
    would drag `teams_search_messages` — and an administrator's signature on
    `ChannelMessage.Read.All` —
    into a deployment that asked for nothing but `list_chats`."""

    @pytest.mark.usefixtures("registry_of_three")
    async def test_prose_pointing_at_a_tool_this_deployment_lacks_is_reported(self) -> None:
        selection = Selection(
            preset=None, tools=(ALWAYS_ON, _SECOND), permissions=("User.Read",), graph_scopes=()
        )

        manifest = await _manifest_of(
            selection,
            tools={_SECOND: f"Reads what {_THIRD} found."},
        )

        assert (
            f"{_SECOND}'s description mentions {_THIRD}, which this deployment does not expose"
            in _flat(manifest)
        )

    @pytest.mark.usefixtures("registry_of_three")
    async def test_an_argument_description_is_scanned_too(self) -> None:
        selection = Selection(
            preset=None, tools=(ALWAYS_ON, _SECOND), permissions=("User.Read",), graph_scopes=()
        )
        mcp: FastMCP = FastMCP("manifest-under-test", version=_VERSION)

        @mcp.tool(name=_SECOND, description="Reads one thing.")
        def _second(uri: str) -> str:
            """Read it.

            Args:
                uri: the handle, as minted by third_tool.
            """
            return uri

        manifest = await surface_manifest(mcp, selection, version=_VERSION)

        assert f"{_SECOND}'s description mentions {_THIRD}" in _flat(manifest)

    async def test_a_deployment_that_exposes_everything_is_told_nothing(self) -> None:
        """The real registry, because a note here would be a note in production."""
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)
        mcp: FastMCP = FastMCP("manifest-under-test", version=_VERSION)

        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)
            manifest = await surface_manifest(mcp, selection, version=_VERSION)

        assert "does not expose" not in _flat(manifest)

    @pytest.mark.usefixtures("registry_of_three")
    async def test_prose_that_merely_contains_a_tool_name_is_not_a_reference_to_it(self) -> None:
        selection = Selection(
            preset=None, tools=(ALWAYS_ON, _SECOND), permissions=("User.Read",), graph_scopes=()
        )

        manifest = await _manifest_of(
            selection, tools={_SECOND: f"Nothing to do with {_THIRD}s, plural."}
        )

        assert "does not expose" not in _flat(manifest)

    @pytest.mark.usefixtures("registry_of_three")
    async def test_a_reference_to_the_always_on_tool_is_never_a_warning(self) -> None:
        selection = resolve(preset=None, enabled=[ALWAYS_ON])

        manifest = await _manifest_of(
            selection, tools={ALWAYS_ON: f"Who you are. Correlate with {ALWAYS_ON}."}
        )

        assert "does not expose" not in _flat(manifest)


class TestTheManifestRefusesToGuess:
    async def test_a_permission_with_no_verdict_is_an_assertion_and_not_a_shrug(self) -> None:
        selection = Selection(
            preset=None, tools=(ALWAYS_ON,), permissions=("Files.Read.All",), graph_scopes=()
        )

        with pytest.raises(AssertionError, match="no admin-consent verdict for Files.Read.All"):
            await _manifest_of(selection)
