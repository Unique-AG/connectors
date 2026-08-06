"""The structural rules this package's layout depends on.

1. **`features/` must not import `server/`.** `features/` is what the connector does; `server/`
   is how it's exposed over MCP. The server wires features together, so it imports them freely —
   the reverse is an inversion. This used to be a convention and it was already broken once:
   `custom_fields/middleware.py` imported `tools.registry`, which only avoided a circular import
   because `custom_fields/__init__.py` happened not to import the middleware.

2. **`backstop_client/` must not import `features/`.** The HTTP client is infrastructure that
   features consume; it importing one back is the same inversion, and it had the same near-miss.
   `client.py`/`factory.py` imported `features.auth` for the credential type and the auth
   context while `features/auth/provider.py` imported `backstop_client` — a genuine package
   cycle that only worked because `features/auth/__init__.py` is empty. Those two types now live
   in `backstop_client/credential.py` (the context as a Protocol), so the direction is one-way.

3. **`backstop_client/` must not import `config`.** The transport takes
   `BackstopTransportSettings`/`RetrySettings` — its own frozen types, translated from
   `BackstopConfig` by `create_app`. It used to take the `pydantic-settings` model directly, which
   coupled the layer to the env-parsing shape and to every knob on it, including the ones it has
   no business seeing (the service account, the custom-field overrides — both land in a later
   PR). `features/` is deliberately *not* subject to this rule: it may read config freely (see
   `features/__init__.py`), because a feature is allowed to be configured — a transport is only
   allowed to be told.

4. **A package is entered through its `__init__`, never through its modules.** From outside,
   `from backstop_mcp.features.party_resolver import resolve_party` — not
   `...party_resolver.resolve import ...`. Each package's `__all__` is then the whole of what it
   promises, and everything else is free to move.

   Applies to the packages listed in `_PUBLIC_SURFACE_PACKAGES`. `features/` and `server/` are
   not among them: they are groupings whose `__init__` is documentation, so `features.resolution`
   and `server.runtime` are themselves the unit being imported.

All four are asserted by walking the AST rather than importing anything, so a violation is
reported as a failing test with a file and line instead of an ImportError at collection time.
"""

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).parent.parent / "src" / "backstop_mcp"

_FEATURES = _SRC / "features"
_BACKSTOP_CLIENT = _SRC / "backstop_client"
_SERVER_PREFIX = "backstop_mcp.server"
_FEATURES_PREFIX = "backstop_mcp.features"
_CONFIG_MODULE = "backstop_mcp.config"

# Packages that publish a surface: outside code imports the package, never a module inside it.
# Tests are deliberately exempt — they walk `src` only — so the pieces a package composes stay
# directly testable without being callable from production code that should go through the front
# door. A new package belongs here as soon as its `__init__` exports anything (`custom_fields`
# and `data_hygiene` land in later PRs and join this list then).
_PUBLIC_SURFACE_PACKAGES: tuple[str, ...] = (
    "backstop_mcp.backstop_client",
    "backstop_mcp.db",
    "backstop_mcp.features.auth",
    "backstop_mcp.features.party_resolver",
    "backstop_mcp.server.middleware",
    "backstop_mcp.server.tools",
)


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
    """Test id for one module: `features/party_resolver/resolve.py`, not an absolute path."""
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
    """`backstop_mcp.features.party_resolver` → the directory that package's modules live in."""
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
        # Verbatim shape of the import that `custom_fields/middleware.py` used to carry.
        assert _imports_under(
            "from backstop_mcp.server.tools.registry import TOOLS",
            _SERVER_PREFIX,
        ) == ["backstop_mcp.server.tools.registry"]

    def test_catches_the_violation_the_backstop_client_rule_exists_for(self) -> None:
        # Verbatim shape of the imports `client.py`/`factory.py` used to carry.
        assert _imports_under(
            "from backstop_mcp.features.auth.crypto import BackstopCredentialSecret\n"
            + "from backstop_mcp.features.auth.context import BackstopAuthContext\n",
            _FEATURES_PREFIX,
        ) == ["backstop_mcp.features.auth.crypto", "backstop_mcp.features.auth.context"]

    def test_catches_a_plain_import_too(self) -> None:
        assert _imports_under("import backstop_mcp.server.runtime", _SERVER_PREFIX) == [
            "backstop_mcp.server.runtime"
        ]

    def test_does_not_fire_on_permitted_imports(self) -> None:
        assert not _imports_under(
            "from backstop_mcp.backstop_client.client import BackstopClient\n"
            + "from backstop_mcp.features.party_resolver.resolve import resolve_party\n"
            + "from backstop_mcp.logging import configure_logging\n",
            _SERVER_PREFIX,
        )

    def test_catches_the_violation_the_config_rule_exists_for(self) -> None:
        # Verbatim shape of the import `client.py`/`factory.py`/`retry.py` used to carry.
        assert _imports_under("from backstop_mcp.config import BackstopConfig", _CONFIG_MODULE) == [
            "backstop_mcp.config"
        ]

    def test_catches_the_violation_the_internals_rule_exists_for(self) -> None:
        assert _internal_imports(
            "from backstop_mcp.features.party_resolver.resolve import resolve_party",
            _SRC / "server" / "tools",
        ) == [("backstop_mcp.features.party_resolver.resolve", 1)]

    def test_the_same_import_is_fine_inside_the_feature(self) -> None:
        assert not _internal_imports(
            "from backstop_mcp.features.party_resolver.resolve import resolve_party",
            _package_directory("backstop_mcp.features.party_resolver"),
        )

    def test_catches_reaching_past_the_init_for_a_service_too(self) -> None:
        """Not only the pure pieces: `search` is behind the front door as well."""
        assert _internal_imports(
            "from backstop_mcp.features.party_resolver.search import search_parties",
            _SRC / "server",
        ) == [("backstop_mcp.features.party_resolver.search", 1)]

    def test_does_not_fire_on_the_package_root(self) -> None:
        assert not _internal_imports(
            "from backstop_mcp.features.party_resolver import resolve_party\n"
            + "from backstop_mcp.server.runtime import get_services\n"
            + "from backstop_mcp.features.resolution import Resolved\n",
            _SRC / "server" / "tools",
        )

    def test_does_not_fire_on_a_name_that_merely_starts_with_the_prefix(self) -> None:
        assert not _imports_under("from backstop_mcp.serverless import thing", _SERVER_PREFIX)
        assert not _imports_under("from backstop_mcp.featureset import thing", _FEATURES_PREFIX)
        assert not _imports_under("from backstop_mcp.configuration import thing", _CONFIG_MODULE)


class TestFeaturesDoNotImportServer:
    def test_the_feature_tree_is_actually_there(self) -> None:
        """Guards the guard: a moved/renamed tree must not silently vacate the rule below."""
        sources = sorted(_FEATURES.rglob("*.py"))
        assert sources, f"no python sources found under {_FEATURES}"
        packages = {p.relative_to(_FEATURES).parts[0] for p in sources if p.name != "__init__.py"}
        assert {"auth", "party_resolver"} <= packages

    @pytest.mark.parametrize("source", sorted(_FEATURES.rglob("*.py")), ids=_source_id)
    def test_no_feature_module_imports_from_server(self, source: pathlib.Path) -> None:
        violations = _violations(source, _SERVER_PREFIX)
        assert not violations, (
            "features/ must not import from server/ — the server wires features together, "
            + "not the reverse. Inject the collaborator from create_app() instead:\n  "
            + "\n  ".join(violations)
        )


class TestBackstopClientDoesNotImportFeatures:
    def test_the_client_tree_is_actually_there(self) -> None:
        """Guards the guard, same as above."""
        sources = sorted(_BACKSTOP_CLIENT.rglob("*.py"))
        assert sources, f"no python sources found under {_BACKSTOP_CLIENT}"
        modules = {p.name for p in sources}
        assert {"client.py", "factory.py", "credential.py"} <= modules

    @pytest.mark.parametrize("source", sorted(_BACKSTOP_CLIENT.rglob("*.py")), ids=_source_id)
    def test_no_client_module_imports_from_features(self, source: pathlib.Path) -> None:
        violations = _violations(source, _FEATURES_PREFIX)
        assert not violations, (
            "backstop_client/ must not import from features/ — it is infrastructure features "
            + "consume, and importing one back is a package cycle. Put the shared type in "
            + "backstop_client/credential.py (a Protocol, if features owns the "
            + "implementation):\n  "
            + "\n  ".join(violations)
        )


class TestBackstopClientDoesNotImportConfig:
    def test_the_settings_module_is_actually_there(self) -> None:
        """Guards the guard: without somewhere to put them, the rule below is unsatisfiable."""
        assert (_BACKSTOP_CLIENT / "settings.py").is_file()

    @pytest.mark.parametrize("source", sorted(_BACKSTOP_CLIENT.rglob("*.py")), ids=_source_id)
    def test_no_client_module_imports_config(self, source: pathlib.Path) -> None:
        violations = _violations(source, _CONFIG_MODULE)
        assert not violations, (
            "backstop_client/ must not import config — it takes its own frozen settings types "
            + "from backstop_client/settings.py, which create_app translates BackstopConfig "
            + "into. Add the field to BackstopTransportSettings (or RetrySettings) and map it "
            + "in app.transport_settings instead:\n  "
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

    def test_a_package_still_composes_its_own_modules(self) -> None:
        """The rule is only meaningful if something inside the package assembles the parts."""
        init = _package_directory("backstop_mcp.features.party_resolver") / "__init__.py"
        imported = {module for module, _line in _imported_modules(ast.parse(init.read_text()))}

        assert "backstop_mcp.features.party_resolver.resolve" in imported

    @pytest.mark.parametrize("source", sorted(_SRC.rglob("*.py")), ids=_source_id)
    def test_no_module_reaches_past_another_packages_init(self, source: pathlib.Path) -> None:
        violations = _internal_module_violations(source)
        assert not violations, (
            "import the package, not a module inside it — a package's __all__ is the whole of "
            + "what it promises, and reaching past it means assembling collaborators the package "
            + "is responsible for assembling. Export the name from that package's __init__ and "
            + "import it from there:\n  "
            + "\n  ".join(violations)
        )
