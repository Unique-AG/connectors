"""The Terraform module's copy of the tool registry, checked against the registry itself.

`deploy/terraform/azure/office-365-mcp-entra-application/registry.tf` states, in HCL, what
`tools/__init__.py`, `shared/seam.py` and `server/manifest.py` state in Python: which tools exist,
which delegated Graph permissions each declares, what every preset means, which permissions this
connector may ever ask for, and which of them need an Entra administrator. It is written out rather
than generated, for the reason `test_tool_selection.py` gives above `PRESET_COST` — a derivation
agrees with any mistake in what it derives from — and this file is what turns two copies into a
check.

Two copies matter here more than anywhere else in this service, because they are two halves of one
sentence spoken in two repositories. The app registration is written by Terraform; the pod's
selection is written by an Argo overlay. A registration narrower than the pod fails every sign-in at
the *authorize* hop, with nothing in this server's logs; a registration wider than the pod grants
standing tenant-wide delegated access that nothing spends. Neither is visible from inside the
server, which is why this is a test and not a paragraph.

What it cannot see: whether the deployed registration and the deployed pod agree. That is one
`terraform apply` and one Argo sync apart, in two other repositories. The module's README documents
diffing `GET /manifest` against `terraform output tool_surface` for it.
"""

import importlib
import json
import pathlib
import re
from collections.abc import Mapping
from typing import Protocol, cast

import pytest

import office_365_mcp.app as app_module
from office_365_mcp.config import ToolsPreset
from office_365_mcp.server.manifest import NEEDS_ADMIN_CONSENT
from office_365_mcp.shared.seam import REQUESTABLE_PERMISSIONS, graph_scope
from office_365_mcp.tools import ALWAYS_ON, PRESETS, TOOL_NAMES, resolve
from tests.test_tool_selection import PRESET_COST

_SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MODULE = _SERVICE_ROOT / "deploy" / "terraform" / "azure" / "office-365-mcp-entra-application"
_REGISTRY_TF = _MODULE / "registry.tf"
_SURFACE_TFTEST = _MODULE / "tests" / "surface.tftest.hcl"
_AUTH = _SERVICE_ROOT / "src" / "office_365_mcp" / "auth.py"
_CHART_SCHEMA = (
    _SERVICE_ROOT / "deploy" / "helm-charts" / "office-365-mcp" / "values.additional.schema.json"
)

# `{ name = "get_me", permissions = ["User.Read"] },` — one row per line, which `terraform fmt` was
# checked to leave byte-identical. Whitespace-tolerant around every `=` because fmt aligns them
# inside a map block, and every assertion below is guarded by a row count so a formatting change
# that breaks these patterns fails loudly rather than matching nothing and passing.
_TOOL_ROW = re.compile(
    r'\{\s*name\s*=\s*"(?P<name>[a-z_]+)"\s*,\s*permissions\s*=\s*\[(?P<permissions>[^]]*)\]\s*\}'
)
# `teams-chat = ["list_chats"]`, or `teams = local.tool_names` for the one derived preset.
_PRESET_ROW = re.compile(
    r"^\s*(?P<name>[a-z][a-z-]*)\s*=\s*(?:\[(?P<names>[^]]*)\]|(?P<derived>local\.tool_names))\s*$",
    re.MULTILINE,
)
_VERDICT_ROW = re.compile(
    r'^\s*"(?P<permission>[A-Za-z.]+)"\s*=\s*(?P<verdict>true|false)\s*$', re.MULTILINE
)
_QUOTED = re.compile(r'"([^"]*)"')
_REQUIRED_SCOPES = re.compile(r'_REQUIRED_SCOPES\s*=\s*\(\s*"(?P<scope>[a-z_]+)"\s*,\s*\)')


class _ToolModule(Protocol):
    """The part of a tool module's contract this file reads; `tools/__init__.py` owns the whole."""

    TOOL_NAME: str
    GRAPH_PERMISSIONS: tuple[str, ...]


def _tool_modules() -> dict[str, tuple[str, ...]]:
    """Found on disk, not through the registry — the same idiom `test_app.py` uses, and for the same
    reason: the point is to see a tool file the registry forgot."""
    tools_dir = pathlib.Path(app_module.__file__).parent / "tools"
    modules = [
        cast(
            "_ToolModule",
            # Through `object`: a `ModuleType` never structurally overlaps a Protocol.
            cast("object", importlib.import_module(f"office_365_mcp.tools.{source.stem}")),
        )
        for source in sorted(tools_dir.glob("*.py"))
        if source.name != "__init__.py"
    ]
    return {module.TOOL_NAME: module.GRAPH_PERMISSIONS for module in modules}


def _block(source: str, name: str, opener: str, closer: str) -> str:
    """The body of `name = <opener> … <closer>`, matched by depth so a nested list is not truncated
    at the first closer. Asserts rather than returns None: a renamed local has to fail here, before
    any comparison can quietly find nothing."""
    start = source.find(f"{name} = {opener}")
    assert start != -1, f"registry.tf has no `{name} = {opener}` — was the local renamed?"
    cursor = start + len(f"{name} = ")
    depth = 0
    for index in range(cursor, len(source)):
        if source[index] == opener:
            depth += 1
        elif source[index] == closer:
            depth -= 1
            if depth == 0:
                return source[cursor + 1 : index]
    raise AssertionError(f"registry.tf's `{name}` block is not closed")


def _registry() -> str:
    return _REGISTRY_TF.read_text()


def _tf_tool_registry() -> list[tuple[str, tuple[str, ...]]]:
    body = _block(_registry(), "tool_registry", "[", "]")
    return [
        (match.group("name"), tuple(_QUOTED.findall(match.group("permissions"))))
        for match in _TOOL_ROW.finditer(body)
    ]


def _tf_presets() -> dict[str, tuple[str, ...]]:
    """`teams` is `local.tool_names` in the HCL, mirroring `PRESETS["teams"] = TOOL_NAMES`, so it is
    expanded here from the parsed registry rather than compared as a token. Keeping the derived form
    in the module is the point: a tool landing in the registry widens `teams` in both places at
    once, exactly as it does in the pod."""
    body = _block(_registry(), "presets", "{", "}")
    rows = list(_PRESET_ROW.finditer(body))
    derived = [match.group("name") for match in rows if match.group("derived") is not None]

    assert derived == ["teams"], (
        "exactly one preset is expected to be derived from the registry, and it is `teams` — "
        + f"found {derived}. Anything else means this expansion is matching the wrong rows."
    )

    registry_order = tuple(name for name, _permissions in _tf_tool_registry())
    return {
        match.group("name"): (
            registry_order
            if match.group("derived") is not None
            else tuple(_QUOTED.findall(match.group("names")))
        )
        for match in rows
    }


def _tf_requestable_permissions() -> tuple[str, ...]:
    return tuple(_QUOTED.findall(_block(_registry(), "requestable_permissions", "[", "]")))


def _tf_needs_admin_consent() -> dict[str, bool]:
    body = _block(_registry(), "needs_admin_consent", "{", "}")
    return {
        match.group("permission"): match.group("verdict") == "true"
        for match in _VERDICT_ROW.finditer(body)
    }


def _tf_scalar(name: str) -> str:
    match = re.search(rf'^\s*{re.escape(name)}\s*=\s*"([^"]*)"\s*$', _registry(), re.MULTILINE)
    assert match is not None, f"registry.tf has no `{name}` string — was the local renamed?"
    return match.group(1)


def _tf_resolve(selection: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """selection.tf's derivation, reimplemented: the ALWAYS_ON join, a filter over the registry's
    order (never the caller's), and `distinct(flatten(...))`, which keeps first occurrence and is
    what `dict.fromkeys` is in the pod.

    Reimplemented rather than inferred from the tables, because a correct table with a wrong
    derivation asks a tenant for the wrong permissions just as effectively.
    """
    wanted = {_tf_scalar("always_on"), *selection}
    selected = [(name, declared) for name, declared in _tf_tool_registry() if name in wanted]
    permissions = tuple(
        dict.fromkeys(permission for _name, declared in selected for permission in declared)
    )
    return tuple(name for name, _declared in selected), permissions


def _chart_preset_enum() -> list[str]:
    node: object = cast("object", json.loads(_CHART_SCHEMA.read_text()))
    for key in ("properties", "env", "properties", "TOOLS_PRESET", "enum"):
        assert isinstance(node, Mapping), f"the chart schema has no {key} under this path"
        node = cast("Mapping[str, object]", node)[key]
    assert isinstance(node, list), "TOOLS_PRESET carries no enum in the chart schema"
    return [value for value in cast("list[object]", node) if isinstance(value, str)]


class TestTheTablesParseAtAll:
    """Guards, asserted before anything is compared. A `terraform fmt` change or a renamed local
    that broke the patterns above would otherwise match zero rows, and every comparison below would
    pass by comparing nothing.
    """

    def test_the_tool_registry_has_a_row_per_tool(self) -> None:
        assert [name for name, _permissions in _tf_tool_registry()] != []
        assert len(_tf_tool_registry()) == len(TOOL_NAMES)

    def test_every_preset_has_a_row(self) -> None:
        assert len(_tf_presets()) == len(ToolsPreset)

    def test_the_ceiling_and_the_consent_verdicts_have_a_row_each(self) -> None:
        assert len(_tf_requestable_permissions()) == len(REQUESTABLE_PERMISSIONS)
        assert len(_tf_needs_admin_consent()) == len(NEEDS_ADMIN_CONSENT)


class TestTheModuleAsksForWhatTheToolsDeclare:
    def test_the_rows_are_in_the_registrys_order(self) -> None:
        """Order is the one thing a set-shaped copy would lose silently. It decides the order of
        `tool_surface.permissions`, which is the artifact an operator diffs against GET /manifest.
        """
        assert tuple(name for name, _permissions in _tf_tool_registry()) == TOOL_NAMES

    def test_every_tool_declares_the_same_permissions_on_both_sides(self) -> None:
        assert dict(_tf_tool_registry()) == _tool_modules()

    def test_the_presets_mean_the_same_thing_on_both_sides(self) -> None:
        assert _tf_presets() == dict(PRESETS)

    def test_the_always_on_tool_is_the_same_tool(self) -> None:
        assert _tf_scalar("always_on") == ALWAYS_ON

    def test_the_ceiling_is_the_same_closed_set(self) -> None:
        """A misspelling in the HCL table satisfies every other check in the module — the index into
        `oauth2_permission_scope_ids` is unknown at plan, so it would fail at apply."""
        assert set(_tf_requestable_permissions()) == set(REQUESTABLE_PERMISSIONS)

    def test_the_admin_consent_verdicts_are_the_same_verdicts(self) -> None:
        """Including the `false` entries: a table holding only the names that need consent could not
        tell "no" from "nobody said", and the module reports the difference to an operator as
        whether an administrator is needed at all."""
        assert _tf_needs_admin_consent() == dict(NEEDS_ADMIN_CONSENT)

    def test_the_graph_scope_prefix_is_the_one_the_server_asks_with(self) -> None:
        assert f"{_tf_scalar('graph_scope_prefix')}User.Read" == graph_scope("User.Read")

    def test_the_api_scope_is_the_one_the_provider_enforces(self) -> None:
        """`access_as_user` is hard-coded in the application, so a registration exposing any other
        name leaves every request failing FastMCP's own scope check with nothing here wrong."""
        match = _REQUIRED_SCOPES.search(_AUTH.read_text())

        assert match is not None, "auth.py no longer spells _REQUIRED_SCOPES as a one-tuple"
        assert _tf_scalar("api_scope_name") == match.group("scope")

    def test_the_callback_path_is_the_one_the_provider_uses(self) -> None:
        """Text-level, and a tripwire rather than a barrier: the path is FastMCP's default and
        auth.py's `build_auth` names it in the contract it documents. A registration carrying any
        other path applies cleanly and then fails every sign-in."""
        assert _tf_scalar("callback_path") in _AUTH.read_text()


class TestTheModuleResolvesASelectionTheWayTheServerDoes:
    """Checks the derivation and not only the data. A correct table filtered in the caller's order,
    or deduped with a set, would ask a tenant for a different permission list than the pod computes
    — and the consent screen and every cached On-Behalf-Of token key are keyed by that list.
    """

    @pytest.mark.parametrize("preset", list(ToolsPreset))
    def test_a_preset_resolves_to_the_same_tools_and_permissions(self, preset: ToolsPreset) -> None:
        expected = resolve(preset=preset, enabled=None)
        tools, permissions = _tf_resolve(_tf_presets()[preset.value])

        assert tools == expected.tools
        assert permissions == expected.permissions

    def test_the_callers_order_is_discarded(self) -> None:
        forwards = _tf_resolve(("list_chats", "read_message"))
        backwards = _tf_resolve(("read_message", "list_chats"))

        expected = resolve(preset=None, enabled=["read_message", "list_chats"])

        assert forwards == backwards
        assert forwards == (expected.tools, expected.permissions)

    def test_the_always_on_tool_joins_a_selection_that_does_not_name_it(self) -> None:
        tools, permissions = _tf_resolve(("list_teams",))

        assert tools[0] == ALWAYS_ON
        assert permissions[0] == "User.Read"


class TestWhatTheModuleCostsATenant:
    """The third leg. `PRESET_COST` is this suite's hand-transcribed table of what each preset asks
    a tenant for; reading it here rather than copying it is deliberate — a fourth copy of the same
    fact would be one more thing to keep in step and no more witnesses.
    """

    @pytest.mark.parametrize(("preset", "permissions", "consents", "tools"), PRESET_COST)
    def test_it_asks_for_exactly_the_permissions_the_design_promises(
        self, preset: ToolsPreset, permissions: tuple[str, ...], consents: int, tools: int
    ) -> None:
        resolved_tools, resolved_permissions = _tf_resolve(_tf_presets()[preset.value])
        verdicts = _tf_needs_admin_consent()
        needing_an_administrator = [
            permission for permission in resolved_permissions if verdicts[permission]
        ]

        assert set(resolved_permissions) == set(permissions)
        assert len(needing_an_administrator) == consents
        assert len(resolved_tools) == tools


class TestTheThreePlacesThePresetNamesAreWritten:
    def test_the_chart_the_module_and_the_enum_name_the_same_presets(self) -> None:
        """The chart schema carries the preset names as a JSON Schema enum, so a name only spelled
        correctly in two of the three places fails a `helm install` or a `terraform apply` rather
        than a sign-in — but only if something compares all three."""
        assert {preset.value for preset in ToolsPreset} == set(_tf_presets())
        assert {preset.value for preset in ToolsPreset} == set(_chart_preset_enum())


class TestTheTerraformTestsExpectWhatTheServerResolves:
    """`surface.tftest.hcl` transcribes a permission string per preset. Those strings are what prove
    the module's HCL derivation is right, so they are checked here against `resolve()` itself — a
    transcription there, a derivation here.
    """

    def test_every_preset_is_exercised_with_the_permissions_it_resolves_to(self) -> None:
        blocks = _SURFACE_TFTEST.read_text().split('\nrun "')
        expectations: dict[str, str] = {}
        for block in blocks[1:]:
            preset = re.search(r'tools_preset\s*=\s*"([a-z-]+)"', block)
            composed = re.search(r'join\(",", local\.permissions\) == "([^"]*)"', block)
            if preset is None or composed is None:
                continue
            expectations[preset.group(1)] = composed.group(1)

        assert set(expectations) == {preset.value for preset in ToolsPreset}, (
            "every preset needs a run block asserting the permissions it composes; the module's "
            + "derivation is the hand-written half and this is what checks it"
        )
        for name, composed in expectations.items():
            expected = ",".join(resolve(preset=name, enabled=None).permissions)

            assert composed == expected, f"{name} is asserted as {composed}, resolves to {expected}"

    def test_the_authorize_requests_spelling_is_asserted_somewhere(self) -> None:
        """`local.graph_scopes` is the one derived value in selection.tf that feeds an output nobody
        else checks: `admin_consent_url`'s `scope=`. Asserting the prefix constant alone left a
        corrupted interpolation — a stray slash, a dropped prefix — passing both gates while making
        every scope in that URL malformed, and that URL is the only consent path there is when
        `service_principal_configuration` is null. So the tftest transcribes the full spelling for
        one preset and this checks the transcription against `graph_scope()` itself.
        """
        asserted = re.search(
            r'join\(" ", local\.graph_scopes\) == "([^"]*)"', _SURFACE_TFTEST.read_text()
        )

        assert asserted is not None, (
            'no run block asserts join(" ", local.graph_scopes); without it the scope= query '
            + "parameter of admin_consent_url is ungated"
        )
        scopes = asserted.group(1).split(" ")
        prefix = _tf_scalar("graph_scope_prefix")
        permissions = [scope.removeprefix(prefix) for scope in scopes]

        assert scopes == [graph_scope(permission) for permission in permissions], (
            f"the asserted spelling {asserted.group(1)} is not what graph_scope() produces"
        )
        assert permissions == list(resolve(preset="teams-chat", enabled=None).permissions), (
            "the run block asserting graph_scopes no longer covers the teams-chat selection"
        )
