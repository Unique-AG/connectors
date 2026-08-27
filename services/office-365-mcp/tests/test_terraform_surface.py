"""The Terraform module's registry, and the three things generating it cannot check.

`deploy/terraform/azure/office-365-mcp-entra-application/registry.generated.tf.json` states, in
Terraform's JSON configuration syntax, what `tools/__init__.py`, `shared/seam.py` and
`server/manifest.py` state in Python: which tools exist, which delegated Graph permissions each
declares, what every preset means, which permissions this connector may ever ask for, and which of
them need an Entra administrator. `scripts/render-terraform-registry.py` writes it from those
modules, so comparing the tables here would compare the generator with itself. What this file checks
is the drift — a committed file the generator would no longer produce — and the facts the generator
is not the writer of.

Those facts matter here more than anywhere else in this service, because they are two halves of one
sentence spoken in two repositories. The app registration is written by Terraform; the pod's
selection is written by an Argo overlay. A registration narrower than the pod fails every sign-in at
the *authorize* hop, with nothing in this server's logs; a registration wider than the pod grants
standing tenant-wide delegated access that nothing spends. Neither is visible from inside the
server, which is why this is a test and not a paragraph.

What it cannot see: whether the deployed registration and the deployed pod agree. That is one
`terraform apply` and one Argo sync apart, in two other repositories. The module's README documents
diffing `GET /manifest` against `terraform output tool_surface` for it.
"""

import importlib.util
import json
import pathlib
import re
from collections.abc import Mapping
from typing import Protocol, cast

from office_365_mcp.config import ToolsPreset
from office_365_mcp.shared.seam import graph_scope
from office_365_mcp.tools import resolve

_SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MODULE = _SERVICE_ROOT / "deploy" / "terraform" / "azure" / "office-365-mcp-entra-application"
_GENERATED = _MODULE / "registry.generated.tf.json"
_GENERATOR = _SERVICE_ROOT / "scripts" / "render-terraform-registry.py"
_SURFACE_TFTEST = _MODULE / "tests" / "surface.tftest.hcl"
_AUTH = _SERVICE_ROOT / "src" / "office_365_mcp" / "auth.py"
_CHART_SCHEMA = (
    _SERVICE_ROOT / "deploy" / "helm-charts" / "office-365-mcp" / "values.additional.schema.json"
)

_REQUIRED_SCOPES = re.compile(r'_REQUIRED_SCOPES\s*=\s*\(\s*"(?P<scope>[a-z_]+)"\s*,\s*\)')
_CALLBACK_PATH = re.compile(r'^_CALLBACK_PATH\s*=\s*"(?P<path>[^"]*)"\s*$', re.MULTILINE)


class _Generator(Protocol):
    """The part of `scripts/render-terraform-registry.py` this file drives; the script owns the
    rest. Loaded by path because the filename carries hyphens, mirroring the shell generator it was
    modelled on."""

    @staticmethod
    def render() -> str: ...


def _generator() -> _Generator:
    spec = importlib.util.spec_from_file_location("render_terraform_registry", _GENERATOR)

    assert spec is not None and spec.loader is not None, (
        f"{_GENERATOR.name} could not be loaded as a module — was it renamed or moved?"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Through `object`: a `ModuleType` never structurally overlaps a Protocol.
    return cast("_Generator", cast("object", module))


def _locals() -> Mapping[str, object]:
    """The committed file's one `locals` block, read rather than regenerated, so every check below
    is against the artifact Terraform actually loads."""
    document: object = cast("object", json.loads(_GENERATED.read_text()))

    assert isinstance(document, Mapping), f"{_GENERATED.name} is not a JSON object"
    blocks = cast("Mapping[str, object]", document).get("locals")

    assert isinstance(blocks, list) and len(cast("list[object]", blocks)) == 1, (
        f"{_GENERATED.name} is expected to carry exactly one `locals` block"
    )
    block = cast("list[object]", blocks)[0]

    assert isinstance(block, Mapping), f"{_GENERATED.name}'s `locals` block is not a JSON object"
    return cast("Mapping[str, object]", block)


def _scalar(name: str) -> str:
    value = _locals().get(name)

    assert isinstance(value, str), (
        f"{_GENERATED.name} has no `{name}` string — was the local renamed?"
    )
    return value


def _chart_preset_enum() -> list[str]:
    node: object = cast("object", json.loads(_CHART_SCHEMA.read_text()))
    for key in ("properties", "mcpConfig", "properties", "tools", "properties", "preset", "enum"):
        assert isinstance(node, Mapping), f"the chart schema has no {key} under this path"
        node = cast("Mapping[str, object]", node)[key]
    assert isinstance(node, list), "tools.preset carries no enum in the chart schema"
    return [value for value in cast("list[object]", node) if isinstance(value, str)]


class TestTheCommittedRegistryIsTheGeneratedOne:
    def test_it_is_byte_for_byte_what_the_generator_produces(self) -> None:
        """`--check` in process, so a stale generated file fails this suite and not only the CI step
        that runs the script — and so a hand-edit of a file whose only warning is `.generated.` in
        its name fails before it reaches a tenant."""
        assert _GENERATED.read_text() == _generator().render(), (
            f"{_GENERATED.name} is not what the registry renders to. It is generated: run "
            + "`uv run python scripts/render-terraform-registry.py` rather than editing it."
        )

    def test_the_registry_names_no_variable(self) -> None:
        """What licenses a `variable ... validation` block in variables.tf reading these locals. A
        `.tf.json` string is still a template, so `"${var.x}"` would interpolate exactly as HCL
        does and the guard is no weaker for the file being JSON."""
        assert "var." not in _GENERATED.read_text(), (
            f"{_GENERATED.name} names a variable, so every validation reading its locals is now a "
            + "hard `Cycle: var.tools_enabled (validation), local.asked_for (expand), …`, which "
            + "`terraform validate` refuses outright"
        )


class TestTheRegistrationExposesWhatTheApplicationEnforces:
    """Two strings the generator reads out of `auth.py` and nothing else witnesses: the application
    hard-codes both, so a registration carrying a different one applies cleanly and then fails every
    request, or every sign-in, with nothing in the module wrong.
    """

    def test_the_api_scope_is_the_one_the_provider_enforces(self) -> None:
        match = _REQUIRED_SCOPES.search(_AUTH.read_text())

        assert match is not None, "auth.py no longer spells _REQUIRED_SCOPES as a one-tuple"
        assert _scalar("api_scope_name") == match.group("scope")

    def test_the_callback_path_is_the_one_the_provider_uses(self) -> None:
        """`build_auth` passes this to `AzureProvider` rather than letting it default, so the path
        the registration carries and the path the provider serves are one constant."""
        match = _CALLBACK_PATH.search(_AUTH.read_text())

        assert match is not None, "auth.py no longer spells _CALLBACK_PATH as a module-level string"
        assert _scalar("callback_path") == match.group("path")


class TestTheThreePlacesThePresetNamesAreWritten:
    def test_the_chart_the_module_and_the_enum_name_the_same_presets(self) -> None:
        """The chart schema carries the preset names as a JSON Schema enum, so a name only spelled
        correctly in two of the three places fails a `helm install` or a `terraform apply` rather
        than a sign-in — but only if something compares all three."""
        presets = _locals().get("presets")

        assert isinstance(presets, Mapping), f"{_GENERATED.name} carries no `presets` map"
        assert {preset.value for preset in ToolsPreset} == set(
            cast("Mapping[str, object]", presets)
        )
        assert {preset.value for preset in ToolsPreset} == set(_chart_preset_enum())


class TestTheTerraformTestsExpectWhatTheServerResolves:
    """`surface.tftest.hcl` transcribes a permission string per preset. Those strings are what prove
    the module's HCL derivation is right — the `get_me` floor, the registry-order filter, the fold
    to first occurrence, none of which the generated tables say anything about — so they are checked
    here against `resolve()` itself: a transcription there, a derivation here.
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
        prefix = _scalar("graph_scope_prefix")
        permissions = [scope.removeprefix(prefix) for scope in scopes]

        assert scopes == [graph_scope(permission) for permission in permissions], (
            f"the asserted spelling {asserted.group(1)} is not what graph_scope() produces"
        )
        assert permissions == list(resolve(preset="teams-chat", enabled=None).permissions), (
            "the run block asserting graph_scopes no longer covers the teams-chat selection"
        )
