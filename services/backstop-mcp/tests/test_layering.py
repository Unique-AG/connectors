"""The one structural rule this package's layout depends on.

`features/` is what the connector does; `server/` is how it's exposed over MCP. The server wires
features together, so it imports them freely — the reverse is an inversion. This used to be a
convention and it was already broken once: `custom_fields/middleware.py` imported
`tools.registry`, which only avoided a circular import because `custom_fields/__init__.py`
happened not to import the middleware.

Asserted by walking the AST rather than importing anything, so a violation is reported as a
failing test with a file and line instead of an ImportError at collection time.
"""

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).parent.parent / "src" / "backstop_mcp"

_FEATURES = _SRC / "features"
_SERVER_PREFIX = "backstop_mcp.server"


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


def _feature_sources() -> list[pathlib.Path]:
    return sorted(_FEATURES.rglob("*.py"))


def _source_id(source: pathlib.Path) -> str:
    """Test id for one feature module: `custom_fields/service.py`, not an absolute path."""
    return str(source.relative_to(_FEATURES))


def _server_imports(source: str) -> list[str]:
    """The `server`-rooted modules `source` imports. The rule below is this, over real files."""
    return [
        module
        for module, _line in _imported_modules(ast.parse(source))
        if module == _SERVER_PREFIX or module.startswith(f"{_SERVER_PREFIX}.")
    ]


class TestTheDetectionItself:
    """The rule is only worth having if it fails on the thing it's meant to catch."""

    def test_catches_the_violation_this_rule_exists_for(self) -> None:
        # Verbatim shape of the import that `custom_fields/middleware.py` used to carry.
        assert _server_imports(
            "from backstop_mcp.server.tools.registry import glossary_entities_by_tool_name"
        ) == ["backstop_mcp.server.tools.registry"]

    def test_catches_a_plain_import_too(self) -> None:
        assert _server_imports("import backstop_mcp.server.runtime") == [
            "backstop_mcp.server.runtime"
        ]

    def test_does_not_fire_on_permitted_imports(self) -> None:
        assert not _server_imports(
            "from backstop_mcp.backstop_client.client import BackstopClient\n"
            + "from backstop_mcp.features.custom_fields.service import CustomFieldsService\n"
            + "from backstop_mcp.logging import get_logger\n"
        )

    def test_does_not_fire_on_a_name_that_merely_starts_with_server(self) -> None:
        assert not _server_imports("from backstop_mcp.serverless import thing")


class TestFeaturesDoNotImportServer:
    def test_the_feature_tree_is_actually_there(self) -> None:
        """Guards the guard: a moved/renamed tree must not silently vacate the rule below."""
        sources = _feature_sources()
        assert sources, f"no python sources found under {_FEATURES}"
        packages = {p.relative_to(_FEATURES).parts[0] for p in sources if p.name != "__init__.py"}
        assert {"auth", "custom_fields", "party_resolver"} <= packages

    @pytest.mark.parametrize("source", _feature_sources(), ids=_source_id)
    def test_no_feature_module_imports_from_server(self, source: pathlib.Path) -> None:
        tree = ast.parse(source.read_text(), filename=str(source))
        violations = [
            f"{source.relative_to(_SRC)}:{line} imports {module}"
            for module, line in _imported_modules(tree)
            if module == _SERVER_PREFIX or module.startswith(f"{_SERVER_PREFIX}.")
        ]
        assert not violations, (
            "features/ must not import from server/ — the server wires features together, "
            + "not the reverse. Inject the collaborator from create_app() instead:\n  "
            + "\n  ".join(violations)
        )
