"""The structural rules this package's layout depends on.

1. **`features/` must not import `server/`.** `features/` is what the connector does; `server/`
   is how it's exposed over MCP. The server wires features together, so it imports them freely —
   the reverse is an inversion.

2. **`graph_client/` must not import `features/`.** The Microsoft Graph client is infrastructure
   that features consume; it importing one back is the same inversion.

3. **`graph_client/` must not import `config`.** The transport takes its own frozen settings
   types, translated from the app's config by `create_app`. `features/` is deliberately *not*
   subject to this rule: it may read config freely, because a feature is allowed to be
   configured — a transport is only allowed to be told.

4. **A package is entered through its `__init__`, never through its modules.** Applies to the
   packages listed in `_PUBLIC_SURFACE_PACKAGES`. `features/` is not among them: it is a grouping
   whose `__init__` is documentation, and whose modules are the units features are composed from.

5. **A config class is only instantiated at the composition root.** `create_app` builds each one
   exactly once and injects it; anything downstream constructing its own re-reads the
   environment and so silently ignores what it was given — which is how a tool ends up
   configured differently from the app it runs in. Reading config types (annotations, imports)
   is unrestricted; only *calling* them is the violation. `main.py` is exempt as a process
   entrypoint: it is the root of its own program and hands `create_app` the config it built.

6. **`server/` must not import the Microsoft Graph SDK.** The mirror of rules 2 and 3, from the
   other side: `msgraph` belongs to `graph_client/` (the transport) and `features/` (the requests).
   A tool that reaches for the SDK itself is how Graph knowledge — which endpoint, which `$expand`,
   which permission — ends up spread across the layer whose job is only to expose it, and the
   tool's request then escapes every test that covers the feature.

7. **`features/` must not import FastMCP.** The mirror of rule 1 for the framework rather than for
   this package: a feature answers with its own types or raises a Graph failure, and turning either
   into something an MCP client sees — a `ToolError`, a tool annotation, a schema — is `server/`'s
   job. Without this, "reject a search with no criteria" would sit in the feature as a `ToolError`,
   and the layer that owns the boundary would no longer own its refusals.

8. **`server/` must not import the Graph SDK's request layer either.** Rule 6 one level down.
   `msgraph` is the generated client, but a Graph request is *configured* through `kiota_*` — a
   `RequestConfiguration`, its query parameters, its headers, its middleware options — and all of
   those are reachable without ever spelling `msgraph`. A tool that builds one has put the shape of
   a Graph call in the layer whose only job is to expose it, and rule 6 alone would not notice.

9. **A `teams:///` handle family has exactly one speller.** `features/message_search.py` owns
   `teams:///chats/…` and `teams:///teams/…`; `features/transcripts.py` owns `teams:///meetings/…`
   and `teams:///transcripts/…`. Nothing else in `features/` may spell the scheme at all. A
   handle is minted by the tool that can produce it and parsed by the one grammar that lives with
   it, which is why `message_read` and `channels` take `MessageHandle` from `message_search` and why
   `chats` asks `transcripts` for a meeting handle rather than assembling a URI of its own. Two
   modules that each knew how to write one would be free to disagree, and the disagreement would
   look like a handle that cannot be read — which is exactly the failure the reply shape exists to
   fix. The rule was originally "only `message_search`", and it is a *family* rule rather than a
   module rule because the second family has a different owner for a reason: a meeting is addressed
   by a join URL that only a chat can supply, and the permission a transcript is read under is
   nothing to do with the one a message is read under. Widening it to "any feature may write a
   handle" is what it must never become. `server/` is not subject to this: a tool description names
   the shapes so a model knows what it may pass, and that is prose rather than a second
implementation.
Every rule is paired with a guard that fails if the rule has become vacuous — an empty tree to walk,
a missing file to forbid reaching for, a framework nothing imports any more. None of them is
conditional: every package these rules are about now exists, so a rule that stops running is a
failure and not a skip.

All rules are asserted by walking the AST rather than importing anything, so a violation is
reported as a failing test with a file and line instead of an ImportError at collection time.
"""

import ast
import pathlib
import re
import sys

import pytest

_SRC = pathlib.Path(__file__).parent.parent / "src" / "office_mcp"

_FEATURES = _SRC / "features"
_GRAPH_CLIENT = _SRC / "graph_client"
_SERVER = _SRC / "server"
_SERVER_PREFIX = "office_mcp.server"
_FEATURES_PREFIX = "office_mcp.features"
_CONFIG_MODULE = "office_mcp.config"
_GRAPH_SDK = "msgraph"
# The distributions underneath the generated SDK: `kiota_abstractions` is where a
# `RequestConfiguration`, its headers and its request options live, `kiota_http` is the middleware
# pipeline and `msgraph_core` is the request adapter. All three are ways to shape a Graph call
# without importing `msgraph`, which is why rule 8 names them separately from rule 6.
_GRAPH_REQUEST_LAYER: tuple[str, ...] = ("kiota_abstractions", "kiota_http", "msgraph_core")
_MCP_FRAMEWORK = "fastmcp"

# The scheme every handle this connector mints is written in, and which feature module owns which
# family of them. Matched as text rather than through the AST because what rule 9 forbids is a
# handle being *spelled* anywhere else — as an f-string, a format template or a concatenation, each
# of which is a different AST and the same duplication. The family is the first path segment after
# the scheme, which is why the grammars keep their segments distinct.
_HANDLE_SCHEME = "teams:///"
_HANDLE_OWNERS: dict[str, frozenset[str]] = {
    "message_search.py": frozenset({"chats", "teams"}),
    "transcripts.py": frozenset({"meetings", "transcripts"}),
}
_HANDLE_FAMILY = re.compile(re.escape(_HANDLE_SCHEME) + r"([A-Za-z_]*)")

# Packages that publish a surface: outside code imports the package, never a module inside it.
# Tests are deliberately exempt — they walk `src` only — so the pieces a package composes stay
# directly testable without being callable from production code that should go through the front
# door. A new package belongs here as soon as its `__init__` exports anything: `server/` earned
# its place by exporting `ready_response`, `graph_client/` by exporting its transport, and the
# feature packages join as they land.
_PUBLIC_SURFACE_PACKAGES: tuple[str, ...] = (
    "office_mcp.graph_client",
    "office_mcp.server",
)

# The `BaseSettings` classes in config.py, which read the environment when constructed.
_CONFIG_CLASSES = frozenset({"AppConfig", "DatabaseConfig", "EntraConfig"})

# Files allowed to construct one, relative to `_SRC`. Both are the root of a program: `app.py` is
# the composition root, and `main.py` is the server entrypoint that hands it its `AppConfig`.
_COMPOSITION_ROOTS = frozenset({"app.py", "main.py"})


def _imported_modules(tree: ast.AST, package: str | None = None) -> list[tuple[str, int]]:
    """Every module name this file imports, with the line it's imported on.

    A relative import (`level > 0`) is resolved to an absolute dotted name against `package` —
    the importing file's own `__package__` — before it's reported. Without that resolution,
    `from ...server.tools import TOOLS` inside `features/calendar/service.py` would never
    spell `server` at `level == 0` and would be invisible to every rule below. Without a
    `package` (the ad-hoc source snippets in `TestTheDetectionItself` below, which name no real
    file), relative imports are skipped: there is nothing to resolve them against.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is not None:
                    found.append((node.module, node.lineno))
            elif package is not None:
                resolved = _resolved_import_target(package, node.level, node.module)
                if resolved is not None:
                    found.append((resolved, node.lineno))
    return found


def _resolved_import_target(package: str, level: int, module: str | None) -> str | None:
    """The absolute dotted module a relative import's `level`/`module` resolve to.

    Mirrors Python's own relative-import resolution: `level` dots walk up from `package` (the
    importing file's `__package__`) by `level - 1` components, and `module` — if the import
    names one (`from . import x` doesn't) — is appended beneath that. Returns `None` if the
    import walks above the top of the tree, which `ast` parses fine but Python raises
    `ImportError` for at runtime.
    """
    parts = package.split(".")
    remaining = len(parts) - (level - 1)
    if remaining < 0:
        return None
    base = parts[:remaining]
    if module:
        base = base + module.split(".")
    return ".".join(base) if base else None


def _dotted_module(source: pathlib.Path) -> str:
    """The dotted module name `source` would import as, e.g. `office_mcp.features.calendar.service`.

    Found by anchoring on the `office_mcp` directory in `source`'s own path, rather than by
    relativizing against the module-level `_SRC` constant — so a temporary copy of the tree
    (as `TestTheDetectionItself` below uses to prove the escape is caught) resolves the same
    way the real `src/office_mcp` does.
    """
    parts = source.with_suffix("").parts
    module_parts = parts[parts.index("office_mcp") :]
    if module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    return ".".join(module_parts)


def _package_of(source: pathlib.Path) -> str:
    """The value `__package__` has inside `source`, i.e. what its relative imports resolve against.

    For a plain module `foo/bar/baz.py` that's `foo.bar` — the package containing it. For
    `foo/bar/__init__.py` it's `foo.bar` itself, since the module IS the package there.
    """
    module = _dotted_module(source)
    if source.name == "__init__.py":
        return module
    return module.rsplit(".", 1)[0]


def _source_id(source: pathlib.Path) -> str:
    """Test id for one module: `features/calendar/service.py`, not an absolute path."""
    return str(source.relative_to(_SRC))


def _imports_under(source: str, prefix: str, package: str | None = None) -> list[str]:
    """The `prefix`-rooted modules `source` imports. Both rules below are this, over real files."""
    return [
        module
        for module, _line in _imported_modules(ast.parse(source), package)
        if module == prefix or module.startswith(f"{prefix}.")
    ]


def _violations(source: pathlib.Path, prefix: str) -> list[str]:
    tree = ast.parse(source.read_text(), filename=str(source))
    return [
        f"{source.relative_to(_SRC)}:{line} imports {module}"
        for module, line in _imported_modules(tree, _package_of(source))
        if module == prefix or module.startswith(f"{prefix}.")
    ]


def _package_directory(package: str) -> pathlib.Path:
    """`office_mcp.features.calendar` → the directory that package's modules live in."""
    return _SRC.joinpath(*package.split(".")[1:])


def _is_inside(directory: pathlib.Path, package: str) -> bool:
    return directory == _package_directory(package) or directory.is_relative_to(
        _package_directory(package)
    )


def _internal_imports(source: str, directory: pathlib.Path) -> list[tuple[str, int]]:
    """Modules of a public-surface package that `source` reaches past the `__init__` for.

    A file inside a package may import its own package's modules freely — that is the package
    composing itself — so the directory the file lives in, not its name, decides.
    """
    return [
        (module, line)
        for package in _PUBLIC_SURFACE_PACKAGES
        if not _is_inside(directory, package)
        for module, line in _imported_modules(ast.parse(source))
        if module.startswith(f"{package}.")
    ]


def _config_constructions(source: str) -> list[tuple[str, int]]:
    """Calls in `source` that construct a config class, with the line each is on.

    Only calls count. Importing a config type, annotating a parameter with one, or handing one
    to `isinstance` are all how an injected config is *used*, and none of them read the
    environment. `AppConfig.model_validate({...})` is likewise left alone: it validates the data
    it is given rather than gathering its own.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Name) and called.id in _CONFIG_CLASSES:
            found.append((called.id, node.lineno))
        # `config.EntraConfig()` — the same construction reached through its module.
        elif isinstance(called, ast.Attribute) and called.attr in _CONFIG_CLASSES:
            found.append((called.attr, node.lineno))
    return found


def _config_construction_violations(source: pathlib.Path) -> list[str]:
    relative = source.relative_to(_SRC)
    if relative.as_posix() in _COMPOSITION_ROOTS:
        return []
    return [
        f"{relative}:{line} constructs {name}()"
        for name, line in _config_constructions(source.read_text())
    ]


def _internal_module_violations(source: pathlib.Path) -> list[str]:
    return [
        f"{source.relative_to(_SRC)}:{line} imports {module}"
        for module, line in _internal_imports(source.read_text(), source.parent)
    ]


class TestTheDetectionItself:
    """The rules are only worth having if they fail on the things they're meant to catch."""

    def test_catches_the_violation_the_server_rule_exists_for(self) -> None:
        assert _imports_under(
            "from office_mcp.server.tools.registry import TOOLS",
            _SERVER_PREFIX,
        ) == ["office_mcp.server.tools.registry"]

    def test_catches_the_violation_the_graph_client_rule_exists_for(self) -> None:
        assert _imports_under(
            "from office_mcp.features.auth.crypto import CredentialSecret\n"
            + "from office_mcp.features.auth.context import AuthContext\n",
            _FEATURES_PREFIX,
        ) == ["office_mcp.features.auth.crypto", "office_mcp.features.auth.context"]

    def test_catches_a_plain_import_too(self) -> None:
        assert _imports_under("import office_mcp.server.runtime", _SERVER_PREFIX) == [
            "office_mcp.server.runtime"
        ]

    def test_catches_a_relative_import_that_escapes_the_layer(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`from ...server.tools import TOOLS` inside `features/calendar/service.py` never
        spells `server` at `level == 0`, so a level-blind check is silently invisible to exactly
        the violation Rule 1 exists to catch. Proves the fix against the real checker
        (`_violations`, what `test_no_feature_module_imports_from_server` runs) over an actual
        file on disk, not just the resolution helper in isolation.
        """
        src = tmp_path / "office_mcp"
        service = src / "features" / "calendar" / "service.py"
        service.parent.mkdir(parents=True)
        service.write_text("from ...server.tools import TOOLS\n")
        monkeypatch.setattr(sys.modules[__name__], "_SRC", src)

        assert _violations(service, _SERVER_PREFIX) == [
            "features/calendar/service.py:1 imports office_mcp.server.tools"
        ]

    def test_does_not_fire_on_permitted_imports(self) -> None:
        assert not _imports_under(
            "from office_mcp.graph_client.client import GraphClient\n"
            + "from office_mcp.features.calendar.service import CalendarService\n"
            + "from office_mcp.logging import configure_logging\n",
            _SERVER_PREFIX,
        )

    def test_catches_the_violation_the_graph_sdk_rule_exists_for(self) -> None:
        assert _imports_under(
            "from msgraph.generated.models.chat import Chat\nimport msgraph\n", _GRAPH_SDK
        ) == ["msgraph.generated.models.chat", "msgraph"]

    def test_the_graph_sdk_rule_leaves_this_services_own_client_alone(self) -> None:
        """`graph_client` is how `server/` is *supposed* to reach Graph, and `msgraph_core` is a
        different distribution — neither may be mistaken for the SDK itself."""
        assert not _imports_under(
            "from office_mcp.graph_client import graph_client_for\nimport msgraph_core\n",
            _GRAPH_SDK,
        )

    def test_catches_configuring_a_graph_request_without_naming_the_sdk(self) -> None:
        """The escape hatch rule 6 leaves open: this is a Graph request being shaped, and the word
        `msgraph` appears nowhere in it."""
        found = [
            module
            for prefix in _GRAPH_REQUEST_LAYER
            for module in _imports_under(
                "from kiota_abstractions.base_request_configuration import RequestConfiguration\n"
                + "from kiota_abstractions.headers_collection import HeadersCollection\n"
                + "import msgraph_core\n",
                prefix,
            )
        ]

        assert found == [
            "kiota_abstractions.base_request_configuration",
            "kiota_abstractions.headers_collection",
            "msgraph_core",
        ]

    def test_the_request_layer_rule_leaves_unrelated_names_alone(self) -> None:
        assert not [
            module
            for prefix in _GRAPH_REQUEST_LAYER
            for module in _imports_under(
                "from office_mcp.graph_client import graph_client_for\n"
                + "from kiotalike.thing import Thing\n",
                prefix,
            )
        ]

    def test_catches_the_violation_the_mcp_framework_rule_exists_for(self) -> None:
        assert _imports_under(
            "from fastmcp.exceptions import ToolError\nimport fastmcp\n", _MCP_FRAMEWORK
        ) == ["fastmcp.exceptions", "fastmcp"]

    def test_the_mcp_framework_rule_leaves_the_protocol_types_alone(self) -> None:
        """`mcp` is the protocol SDK, a different distribution from the server framework, and a
        name that merely begins with `fastmcp` is not it either."""
        assert not _imports_under(
            "from mcp.types import TextContent\nfrom fastmcpx import thing\n", _MCP_FRAMEWORK
        )

    def test_catches_the_violation_the_config_rule_exists_for(self) -> None:
        assert _imports_under("from office_mcp.config import AppConfig", _CONFIG_MODULE) == [
            "office_mcp.config"
        ]

    def test_catches_the_violation_the_internals_rule_exists_for(self) -> None:
        # `server` stands in for any listed package here; the rule is about the front door, not
        # about which package happens to be behind it. The importing directory is `_SRC` — i.e.
        # `app.py`, the composition root, which is the likeliest place to reach past one.
        assert _internal_imports(
            "from office_mcp.server.readiness import ready_response",
            _SRC,
        ) == [("office_mcp.server.readiness", 1)]

    def test_the_same_import_is_fine_inside_the_package(self) -> None:
        assert not _internal_imports(
            "from office_mcp.server.readiness import ready_response",
            _package_directory("office_mcp.server"),
        )

    def test_catches_reaching_past_the_init_for_a_service_too(self) -> None:
        """Not only one module: every module inside a public-surface package is behind the
        front door, not only the ones with an obviously "internal" name — including the ones
        not written yet, which is why `server.tools` (a later PR's) is named here."""
        assert _internal_imports(
            "from office_mcp.server.tools import TOOLS",
            _SRC / "features",
        ) == [("office_mcp.server.tools", 1)]

    def test_does_not_fire_on_the_package_root(self) -> None:
        assert not _internal_imports(
            "from office_mcp.features.calendar import CalendarService\n"
            + "from office_mcp.server import ready_response\n"
            + "from office_mcp.features.resolution import Resolved\n",
            _SRC,
        )

    def test_catches_the_violation_the_config_construction_rule_exists_for(self) -> None:
        assert _config_constructions(
            "def graph_settings() -> None:\n    entra = EntraConfig()\n"
        ) == [("EntraConfig", 2)]

    def test_catches_a_config_built_through_its_module_too(self) -> None:
        assert _config_constructions("cfg = config.AppConfig()") == [("AppConfig", 1)]

    def test_does_not_fire_on_using_an_injected_config(self) -> None:
        assert not _config_constructions(
            "from office_mcp.config import EntraConfig\n"
            + "def build_auth(entra: EntraConfig) -> str:\n"
            + "    return entra.client_id\n"
        )

    def test_does_not_fire_on_validating_supplied_data(self) -> None:
        """`model_validate` is handed its values; it does not go looking for them."""
        assert not _config_constructions("AppConfig.model_validate({'port': 1})")

    def test_does_not_fire_on_a_name_that_merely_starts_with_the_prefix(self) -> None:
        assert not _imports_under("from office_mcp.serverless import thing", _SERVER_PREFIX)
        assert not _imports_under("from office_mcp.featureset import thing", _FEATURES_PREFIX)
        assert not _imports_under("from office_mcp.configuration import thing", _CONFIG_MODULE)


class TestFeaturesDoNotImportServer:
    def test_the_feature_tree_is_actually_there(self) -> None:
        """Guards the guard: a moved or renamed tree must not silently vacate the rule below.

        The rule is parametrized over `features/`, so an empty tree makes it zero tests that pass
        by not existing. What has to be there is feature *modules* — `features/` is a grouping and
        its units are modules, not subpackages (see rule 4) — so that is what is asserted.
        """
        modules = [p for p in sorted(_FEATURES.rglob("*.py")) if p.name != "__init__.py"]
        assert modules, f"no feature modules found under {_FEATURES}"

    @pytest.mark.parametrize("source", sorted(_FEATURES.rglob("*.py")), ids=_source_id)
    def test_no_feature_module_imports_from_server(self, source: pathlib.Path) -> None:
        violations = _violations(source, _SERVER_PREFIX)
        assert not violations, (
            "features/ must not import from server/ — the server wires features together, "
            + "not the reverse. Inject the collaborator from create_app() instead:\n  "
            + "\n  ".join(violations)
        )


class TestFeaturesDoNotImportTheMcpFramework:
    def test_the_tool_layer_does_import_it(self) -> None:
        """Guards the guard: the rule is about which layer talks to FastMCP, not about the
        framework being unused — if `server/` stopped importing it, this rule would be vacuous."""
        assert _imports_under(
            (_SERVER / "tools.py").read_text(), _MCP_FRAMEWORK, _package_of(_SERVER / "tools.py")
        )

    @pytest.mark.parametrize("source", sorted(_FEATURES.rglob("*.py")), ids=_source_id)
    def test_no_feature_module_imports_the_mcp_framework(self, source: pathlib.Path) -> None:
        violations = _violations(source, _MCP_FRAMEWORK)
        assert not violations, (
            "features/ must not import FastMCP — a feature returns its own types or raises a "
            + "Graph failure, and turning either into something an MCP client sees belongs to "
            + "server/. Return the fact (or raise) and let the tool decide what to say:\n  "
            + "\n  ".join(violations)
        )


class TestGraphClientDoesNotImportFeatures:
    def test_the_client_tree_is_actually_there(self) -> None:
        """Guards the guard, same as above."""
        sources = sorted(_GRAPH_CLIENT.rglob("*.py"))
        assert sources, f"no python sources found under {_GRAPH_CLIENT}"
        modules = {p.name for p in sources}
        assert {"client.py", "settings.py"} <= modules

    @pytest.mark.parametrize("source", sorted(_GRAPH_CLIENT.rglob("*.py")), ids=_source_id)
    def test_no_client_module_imports_from_features(self, source: pathlib.Path) -> None:
        violations = _violations(source, _FEATURES_PREFIX)
        assert not violations, (
            "graph_client/ must not import from features/ — it is infrastructure features "
            + "consume, and importing one back is a package cycle. Put the shared type in "
            + "graph_client/ (a Protocol, if features owns the implementation):\n  "
            + "\n  ".join(violations)
        )


class TestGraphClientDoesNotImportConfig:
    def test_the_settings_module_is_actually_there(self) -> None:
        """Guards the guard: without somewhere to put them, the rule below is unsatisfiable."""
        assert (_GRAPH_CLIENT / "settings.py").is_file()

    @pytest.mark.parametrize("source", sorted(_GRAPH_CLIENT.rglob("*.py")), ids=_source_id)
    def test_no_client_module_imports_config(self, source: pathlib.Path) -> None:
        violations = _violations(source, _CONFIG_MODULE)
        assert not violations, (
            "graph_client/ must not import config — it takes its own frozen settings types "
            + "from graph_client/settings.py, which create_app translates the app config into. "
            + "Add the field to those settings and map it in create_app instead:\n  "
            + "\n  ".join(violations)
        )


class TestTheServerLayerDoesNotSpeakGraph:
    def test_the_tool_module_is_actually_there(self) -> None:
        """Guards the guard: with no tools, nothing in `server/` would be tempted to call Graph
        and the rule below would pass vacuously."""
        assert (_SERVER / "tools.py").is_file()

    @pytest.mark.parametrize("source", sorted(_SERVER.rglob("*.py")), ids=_source_id)
    def test_no_server_module_imports_the_graph_sdk(self, source: pathlib.Path) -> None:
        violations = _violations(source, _GRAPH_SDK)
        assert not violations, (
            "server/ must not import the Microsoft Graph SDK — a tool declares and exposes; the "
            + "request belongs in a feature module and the transport in graph_client/. Move the "
            + "Graph call into features/ and have the tool call that:\n  "
            + "\n  ".join(violations)
        )

    def test_the_layer_that_may_configure_a_request_actually_does(self) -> None:
        """Guards the guard for the rule below: the request layer is used, in `features/`, which is
        where it belongs — so forbidding it in `server/` is a boundary rather than a dead letter."""
        used = [
            module
            for source in sorted(_FEATURES.rglob("*.py"))
            for prefix in _GRAPH_REQUEST_LAYER
            for module in _imports_under(source.read_text(), prefix, _package_of(source))
        ]

        assert used, f"nothing under {_FEATURES} configures a Graph request"

    @pytest.mark.parametrize("source", sorted(_SERVER.rglob("*.py")), ids=_source_id)
    def test_no_server_module_imports_the_graph_request_layer(self, source: pathlib.Path) -> None:
        violations = [
            violation
            for prefix in _GRAPH_REQUEST_LAYER
            for violation in _violations(source, prefix)
        ]
        assert not violations, (
            "server/ must not import the Graph SDK's request layer — a RequestConfiguration, a "
            + "header or a request option is part of a Graph call, and a Graph call belongs in "
            + "features/ however it is spelled. Move it there and have the tool call the "
            + "feature:\n  "
            + "\n  ".join(violations)
        )


class TestEachHandleFamilyHasOneHome:
    @pytest.mark.parametrize("owner", sorted(_HANDLE_OWNERS))
    def test_the_module_that_owns_a_family_actually_writes_it(self, owner: str) -> None:
        """Guards the guard: if a family stopped being minted where the rule says it is, the rule
        would forbid something nothing does and the grammar would have quietly moved."""
        written = set(_HANDLE_FAMILY.findall((_FEATURES / owner).read_text()))

        assert written == _HANDLE_OWNERS[owner], (
            f"{owner} spells the handle families {sorted(written)}, and rule 9 gives it "
            + f"{sorted(_HANDLE_OWNERS[owner])}"
        )

    @pytest.mark.parametrize("source", sorted(_FEATURES.rglob("*.py")), ids=_source_id)
    def test_no_feature_module_writes_another_families_handle(self, source: pathlib.Path) -> None:
        owned = _HANDLE_OWNERS.get(source.name, frozenset())
        trespasses = sorted(set(_HANDLE_FAMILY.findall(source.read_text())) - owned)

        assert not trespasses, (
            f"{source.relative_to(_SRC)} spells the handle families {trespasses}, which it does "
            + f"not own — each family is minted and parsed in one module ({_HANDLE_OWNERS}), and a "
            + "second speller is free to disagree with it. Build that module's handle type and "
            + "read its `uri` instead."
        )


class TestConfigIsBuiltOnlyAtTheCompositionRoot:
    def test_every_exempt_file_actually_exists(self) -> None:
        """Guards the guard: a renamed entrypoint would silently widen the exemption."""
        for relative in sorted(_COMPOSITION_ROOTS):
            assert (_SRC / relative).is_file(), f"no such file: {relative}"

    def test_the_composition_root_really_does_build_every_config(self) -> None:
        """And guards it from the other side: if `app.py` stopped constructing the config
        classes, they would be built somewhere else and this rule would be vacuous."""
        built = {name for name, _line in _config_constructions((_SRC / "app.py").read_text())}

        assert built >= _CONFIG_CLASSES, f"app.py does not build {_CONFIG_CLASSES - built}"

    @pytest.mark.parametrize("source", sorted(_SRC.rglob("*.py")), ids=_source_id)
    def test_no_module_outside_the_root_builds_its_own_config(self, source: pathlib.Path) -> None:
        violations = _config_construction_violations(source)
        assert not violations, (
            "only create_app() may construct a config — building one here re-reads the "
            + "environment and quietly ignores whatever create_app was given. Take the value "
            + "as a parameter and let the composition root pass it in:\n  "
            + "\n  ".join(violations)
        )


class TestPackagesAreEnteredThroughTheirInit:
    def test_every_listed_package_actually_publishes_something(self) -> None:
        """Guards the guard: a package with no `__all__` has no front door to insist on."""
        for package in _PUBLIC_SURFACE_PACKAGES:
            init = _package_directory(package) / "__init__.py"
            assert init.is_file(), f"no __init__.py for {package}"
            exported = [
                node
                for node in ast.walk(ast.parse(init.read_text()))
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                )
            ]
            assert exported, f"{package}/__init__.py declares no __all__"

    @pytest.mark.parametrize("source", sorted(_SRC.rglob("*.py")), ids=_source_id)
    def test_no_module_reaches_past_another_packages_init(self, source: pathlib.Path) -> None:
        violations = _internal_module_violations(source)
        assert not violations, (
            "import the package, not a module inside it — a package's __all__ is the whole of "
            + "what it promises, and reaching past it means assembling collaborators the package "
            + "is responsible for assembling (which is how a tool came to re-read its own config "
            + "and ignore what create_app was given). Export the name from that package's "
            + "__init__ and import it from there:\n  "
            + "\n  ".join(violations)
        )
