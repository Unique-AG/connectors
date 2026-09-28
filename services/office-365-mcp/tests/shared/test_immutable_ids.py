import ast
import pathlib

import pytest

from office_365_mcp.shared.immutable_ids import immutable_id_headers

_SRC = pathlib.Path(__file__).parent.parent.parent / "src" / "office_365_mcp"
_OWNER = _SRC / "shared" / "immutable_ids.py"


def _docstrings(tree: ast.AST) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, owners)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _source_id(source: pathlib.Path) -> str:
    return str(source.relative_to(_SRC))


def _spellings(source: pathlib.Path) -> list[int]:
    tree = ast.parse(source.read_text())
    docstrings = _docstrings(tree)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "ImmutableId" in node.value
        and id(node) not in docstrings
    ]


class TestImmutableIdHeaders:
    def test_asks_graph_for_immutable_ids(self) -> None:
        assert immutable_id_headers().get_all() == {"prefer": {'IdType="ImmutableId"'}}

    def test_every_call_builds_its_own_collection(self) -> None:
        assert immutable_id_headers() is not immutable_id_headers()


class TestOnlyTheOwnerSpellsThePreference:
    def test_the_owner_actually_spells_it(self) -> None:
        assert _spellings(_OWNER)

    @pytest.mark.parametrize(
        "source", [s for s in sorted(_SRC.rglob("*.py")) if s != _OWNER], ids=_source_id
    )
    def test_no_other_module_spells_it(self, source: pathlib.Path) -> None:
        lines = _spellings(source)
        assert not lines, (
            f"{_source_id(source)} contains the ImmutableId preference on lines {lines}. "
            + "Use immutable_id_headers() from shared/immutable_ids.py."
        )
