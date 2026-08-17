"""What an operator is told this deployment resolved to.

The manifest is not a nicety. Nothing in this server can check its own ask against the app
registration — Azure omits Graph scopes from the session token's `scp`, so the grants are invisible
here — and a mismatch fails at the *authorize* hop, which is a login no user can complete, with
nothing in this server's logs to explain it. The exact permission list, and which of it needs an
administrator, exists in one place only, and this is it.

So what is asserted here is that the list is right and that it says who has to sign off. The
wrapping is not: an assertion on where a line breaks is one that fails the day a tool name grows.
"""

import re
from collections.abc import Iterator, Mapping

import httpx
import pytest
from fastmcp import FastMCP

import office_mcp.server.manifest as manifest_module
from office_mcp.config import ToolsPreset
from office_mcp.server import surface_manifest
from office_mcp.server.manifest import NEEDS_ADMIN_CONSENT
from office_mcp.shared.seam import REQUESTABLE_PERMISSIONS
from office_mcp.tools import ALWAYS_ON, Selection, register_tools, resolve

_VERSION = "9.9.9"

_SECOND = "second_tool"
_THIRD = "third_tool"


@pytest.fixture
def registry_of_three(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The registry the scan compares prose against, widened to three tools.

    The scan reports names of tools *this server has* that this deployment did not select, so with
    one tool in the tree — and that one always on — there is never anything to report. Patched where
    the manifest reads it, which is that module's own binding.
    """
    monkeypatch.setattr(manifest_module, "TOOL_NAMES", (ALWAYS_ON, _SECOND, _THIRD))
    yield


async def _manifest_of(selection: Selection, *, tools: Mapping[str, str] | None = None) -> str:
    """The manifest for `selection`, over a server carrying `tools` and their descriptions.

    A real `FastMCP` rather than a stub, because the description scan reads the registered tools'
    own prose and reading it off the server is the whole of what makes the scan true.
    """
    mcp: FastMCP = FastMCP("manifest-under-test", version=_VERSION)
    for name, description in (tools or {}).items():
        _carrying_prose(mcp, name, description)
    return await surface_manifest(mcp, selection, version=_VERSION)


def _flat(manifest: str) -> str:
    """The manifest with its wrapping collapsed, so an assertion is about content, not layout.

    A note is a whole sentence and the block is wrapped, so the words an assertion looks for are
    routinely split across two lines — and where the break falls moves the day a tool name grows.
    """
    return " ".join(manifest.split())


def _carrying_prose(mcp: FastMCP, name: str, description: str) -> None:
    """A tool that exists only to carry a description, which is all the scan reads of one."""

    def _stub() -> str:
        return name

    mcp.tool(name=name, description=description)(_stub)


class TestTheTableAnswersForEveryPermissionAToolCanDeclare:
    """`NEEDS_ADMIN_CONSENT` is hand-written because needing consent is Microsoft's rule about a
    permission and no tool file knows it. This is what stops it drifting behind the tool files."""

    def test_every_permission_this_connector_may_ask_for_has_a_verdict(self) -> None:
        """A permission added without one would make the manifest tell an operator no administrator
        is needed when one is — and then every sign-in stops at "Need admin approval", for a reason
        this server never logs. The `False` entries are what make the difference between "no" and
        "nobody said" visible at all.
        """
        unanswered = sorted(REQUESTABLE_PERMISSIONS - set(NEEDS_ADMIN_CONSENT))

        assert not unanswered, (
            f"{unanswered} can be declared by a tool and reach the consent screen, but "
            + "NEEDS_ADMIN_CONSENT does not say whether an administrator has to grant them. Add "
            + "each one with its verdict from Microsoft's permissions reference"
        )

    def test_it_answers_for_nothing_else(self) -> None:
        """The other direction, which only became assertable in this PR.

        The table was written complete while most of the permissions in it were still ahead of the
        tools that declare them, so for most of this stack a misspelled entry sat unchecked: the
        totality test above is satisfied by the names that *are* requestable, and a wrong one
        simply waits — it would have failed for most of the commits behind this one. The eighth and
        last permission arrives with the recordings tool, in this same PR, so the two sides can now
        be pinned to each other — and a name in the table no tool can declare is now a failing test
        rather than an `AssertionError` from the manifest the day its tool lands.
        """
        unrequestable = sorted(set(NEEDS_ADMIN_CONSENT) - REQUESTABLE_PERMISSIONS)

        assert not unrequestable, (
            f"NEEDS_ADMIN_CONSENT answers for {unrequestable}, which no tool may declare — either "
            + "the spelling is wrong, or the permission was removed and its verdict left behind"
        )

    def test_the_verdicts_are_not_all_the_same_answer(self) -> None:
        """Guards the guard: a table of all-`False` would satisfy the totality check above while
        telling every operator that no permission ever needs an administrator."""
        assert set(NEEDS_ADMIN_CONSENT.values()) == {True, False}


class TestWhatTheManifestSays:
    async def test_it_names_the_variable_that_produced_the_surface(self) -> None:
        """So the loop closes: an operator reads which knob is live, then the tools it resolved to,
        and can paste the second into `TOOLS_ENABLED` to narrow it further."""
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
        """Entra's spelling and not the scope URL: this line is what an operator hands their
        administrator, who reads `User.Read` in the portal and not a scope."""
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
        """Which is the answer for the narrow deployments this feature exists for, so it has to be
        stated rather than left as a blank line an operator has to interpret."""
        selection = resolve(preset=None, enabled=[ALWAYS_ON])

        manifest = await _manifest_of(selection)

        assert re.search(r"admin consent\s+none", manifest)

    async def test_it_carries_no_consent_url(self) -> None:
        """Deliberately: `/.default` would consent to whatever the registration happens to carry
        rather than to what this deployment asks for, and a scope-matched admin-consent URL needs a
        `redirect_uri` matching a registered one — and the only one office-mcp registers is
        FastMCP's OAuth callback, which would render a successful consent as an error."""
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        manifest = await _manifest_of(selection)

        assert "adminconsent" not in manifest
        assert "login.microsoftonline.com" not in manifest
        assert "https://" not in manifest

    async def test_it_carries_the_version_that_resolved_it(self) -> None:
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        manifest = await _manifest_of(selection)

        assert manifest.startswith(f"office-mcp {_VERSION} —")


class TestTheDescriptionScanWarnsAboutStalePromises:
    """A tool named in an exposed tool's prose that this deployment does not expose. It warns and
    never aborts: the references are dense and mutual, so requiring every mention would drag
    `search_messages` — and with it an administrator's signature on `ChannelMessage.Read.All` — into
    a deployment that asked for nothing but `list_chats`.
    """

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
        """Where it matters most: an argument's description is where a tool names the tool that
        mints the handle it takes, so scanning tool descriptions alone would miss the references a
        model is most likely to act on."""
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
        """Nothing is missing, so there is nothing to warn about — and the real registry is what
        proves it, because a note here would be a note in production."""
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)
        mcp: FastMCP = FastMCP("manifest-under-test", version=_VERSION)

        async with httpx.AsyncClient() as transport:
            register_tools(mcp, transport, selection)
            manifest = await surface_manifest(mcp, selection, version=_VERSION)

        assert "does not expose" not in _flat(manifest)

    @pytest.mark.usefixtures("registry_of_three")
    async def test_prose_that_merely_contains_a_tool_name_is_not_a_reference_to_it(self) -> None:
        """A tool name is one word, here as to a reader. `read_message` is not mentioned by prose
        saying `read_messages`, and a note about it would send an operator looking for a reference
        nobody wrote — in a report whose whole value is that every line of it is true."""
        selection = Selection(
            preset=None, tools=(ALWAYS_ON, _SECOND), permissions=("User.Read",), graph_scopes=()
        )

        manifest = await _manifest_of(
            selection, tools={_SECOND: f"Nothing to do with {_THIRD}s, plural."}
        )

        assert "does not expose" not in _flat(manifest)

    @pytest.mark.usefixtures("registry_of_three")
    async def test_a_reference_to_the_always_on_tool_is_never_a_warning(self) -> None:
        """Because it is registered whatever the selection, which is what lets every tool that sends
        a model to it go on saying so in every deployment."""
        selection = resolve(preset=None, enabled=[ALWAYS_ON])

        manifest = await _manifest_of(
            selection, tools={ALWAYS_ON: f"Who you are. Correlate with {ALWAYS_ON}."}
        )

        assert "does not expose" not in _flat(manifest)


class TestTheManifestRefusesToGuess:
    async def test_a_permission_with_no_verdict_is_an_assertion_and_not_a_shrug(self) -> None:
        """The alternative is worse than a crash: a manifest quietly reporting "admin consent: none"
        for a permission that needs one sends an operator to their administrator with nothing to
        grant, and every sign-in then fails for a reason this server never logs."""
        selection = Selection(
            preset=None, tools=(ALWAYS_ON,), permissions=("Mail.Read",), graph_scopes=()
        )

        with pytest.raises(AssertionError, match="no admin-consent verdict for Mail.Read"):
            await _manifest_of(selection)
