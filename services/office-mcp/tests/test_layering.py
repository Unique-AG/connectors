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
   packages listed in `_PUBLIC_SURFACE_PACKAGES`. `features/` and `server/` are not among them:
   they are groupings whose `__init__` is documentation.

Rules 2 and 3 only apply to `graph_client/`, which doesn't exist yet in this PR — those test
classes no-op (skip) until it lands. Rule 1's "the tree actually has feature packages" guard
similarly skips until the first feature package exists; the import-direction check itself still
runs against whatever *is* under `features/` (currently just `__init__.py`, which trivially
passes).

All rules are asserted by walking the AST rather than importing anything, so a violation is
reported as a failing test with a file and line instead of an ImportError at collection time.
"""

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).parent.parent / "src" / "office_mcp"

_FEATURES = _SRC / "features"
_GRAPH_CLIENT = _SRC / "graph_client"
_SERVER_PREFIX = "office_mcp.server"
_FEATURES_PREFIX = "office_mcp.features"
_CONFIG_MODULE = "office_mcp.config"

# Packages that publish a surface: outside code imports the package, never a module inside it.
# Tests are deliberately exempt — they walk `src` only — so the pieces a package composes stay
# directly testable without being callable from production code that should go through the front
# door. A new package belongs here as soon as its `__init__` exports anything.
_PUBLIC_SURFACE_PACKAGES: tuple[str, ...] = ("office_mcp.db",)


def _feature_packages() -> set[str]:
    """The subpackages under `features/`. Empty in this PR — the first ones land later."""
    return {p.name for p in _FEATURES.iterdir() if p.is_dir() and p.name != "__pycache__"}


def _imported_modules(tree: ast.AST) -> list[tuple[str, int]]:
    """Every module name this file imports, with the line it's imported on."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        # `level > 0` is a relative import, which can't escape `features/` by name anyway.
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.append((node.module, node.lineno))
    return found


def _source_id(source: pathlib.Path) -> str:
    """Test id for one module: `features/calendar/service.py`, not an absolute path."""
    return str(source.relative_to(_SRC))


def _imports_under(source: str, prefix: str) -> list[str]:
    """The `prefix`-rooted modules `source` imports. Both rules below are this, over real files."""
    return [
        module
        for module, _line in _imported_modules(ast.parse(source))
        if module == prefix or module.startswith(f"{prefix}.")
    ]


def _violations(source: pathlib.Path, prefix: str) -> list[str]:
    tree = ast.parse(source.read_text(), filename=str(source))
    return [
        f"{source.relative_to(_SRC)}:{line} imports {module}"
        for module, line in _imported_modules(tree)
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

    def test_does_not_fire_on_permitted_imports(self) -> None:
        assert not _imports_under(
            "from office_mcp.graph_client.client import GraphClient\n"
            + "from office_mcp.features.calendar.service import CalendarService\n"
            + "from office_mcp.logging import configure_logging\n",
            _SERVER_PREFIX,
        )

    def test_catches_the_violation_the_config_rule_exists_for(self) -> None:
        assert _imports_under("from office_mcp.config import AppConfig", _CONFIG_MODULE) == [
            "office_mcp.config"
        ]

    def test_catches_the_violation_the_internals_rule_exists_for(self) -> None:
        # `_PUBLIC_SURFACE_PACKAGES` only lists `db` for now, so that's the stand-in package
        # here; once the first feature package lands and joins the list, its own modules serve
        # this same role.
        assert _internal_imports(
            "from office_mcp.db.engine import create_engine",
            _SRC / "server",
        ) == [("office_mcp.db.engine", 1)]

    def test_the_same_import_is_fine_inside_the_feature(self) -> None:
        assert not _internal_imports(
            "from office_mcp.db.engine import create_engine",
            _package_directory("office_mcp.db"),
        )

    def test_catches_reaching_past_the_init_for_a_service_too(self) -> None:
        """Not only one module: every module inside a public-surface package is behind the
        front door, not only the ones with an obviously "internal" name."""
        assert _internal_imports(
            "from office_mcp.db.models import Base",
            _SRC / "features",
        ) == [("office_mcp.db.models", 1)]

    def test_does_not_fire_on_the_package_root(self) -> None:
        assert not _internal_imports(
            "from office_mcp.features.calendar import CalendarService\n"
            + "from office_mcp.server.runtime import get_services\n"
            + "from office_mcp.features.resolution import Resolved\n",
            _SRC / "server" / "tools",
        )

    def test_does_not_fire_on_a_name_that_merely_starts_with_the_prefix(self) -> None:
        assert not _imports_under("from office_mcp.serverless import thing", _SERVER_PREFIX)
        assert not _imports_under("from office_mcp.featureset import thing", _FEATURES_PREFIX)
        assert not _imports_under("from office_mcp.configuration import thing", _CONFIG_MODULE)


class TestFeaturesDoNotImportServer:
    @pytest.mark.skipif(not _feature_packages(), reason="feature packages land in later PRs")
    def test_the_feature_tree_is_actually_there(self) -> None:
        """Guards the guard: a moved/renamed tree must not silently vacate the rule below."""
        sources = sorted(_FEATURES.rglob("*.py"))
        assert sources, f"no python sources found under {_FEATURES}"
        packages = {p.relative_to(_FEATURES).parts[0] for p in sources if p.name != "__init__.py"}
        assert packages, f"no feature packages found under {_FEATURES}"

    @pytest.mark.parametrize("source", sorted(_FEATURES.rglob("*.py")), ids=_source_id)
    def test_no_feature_module_imports_from_server(self, source: pathlib.Path) -> None:
        violations = _violations(source, _SERVER_PREFIX)
        assert not violations, (
            "features/ must not import from server/ — the server wires features together, "
            + "not the reverse. Inject the collaborator from create_app() instead:\n  "
            + "\n  ".join(violations)
        )


@pytest.mark.skipif(not _GRAPH_CLIENT.is_dir(), reason="graph_client/ lands in a later PR")
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


@pytest.mark.skipif(not _GRAPH_CLIENT.is_dir(), reason="graph_client/ lands in a later PR")
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
