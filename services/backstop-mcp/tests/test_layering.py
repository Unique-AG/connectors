"""The two structural rules this package's layout depends on.

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
   no business seeing (the service account, the custom-field overrides). `features/` is
   deliberately *not* subject to this rule: it may read config freely (see `features/__init__.py`),
   because a feature is allowed to be configured — a transport is only allowed to be told.

All three are asserted by walking the AST rather than importing anything, so a violation is
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
    """Test id for one module: `features/custom_fields/service.py`, not an absolute path."""
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


class TestTheDetectionItself:
    """The rules are only worth having if they fail on the things they're meant to catch."""

    def test_catches_the_violation_the_server_rule_exists_for(self) -> None:
        # Verbatim shape of the import that `custom_fields/middleware.py` used to carry.
        assert _imports_under(
            "from backstop_mcp.server.tools.registry import glossary_entities_by_tool_name",
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
            + "from backstop_mcp.features.custom_fields.service import CustomFieldsService\n"
            + "from backstop_mcp.logging import get_logger\n",
            _SERVER_PREFIX,
        )

    def test_catches_the_violation_the_config_rule_exists_for(self) -> None:
        # Verbatim shape of the import `client.py`/`factory.py`/`retry.py` used to carry.
        assert _imports_under("from backstop_mcp.config import BackstopConfig", _CONFIG_MODULE) == [
            "backstop_mcp.config"
        ]

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
        assert {"auth", "custom_fields", "party_resolver"} <= packages

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
