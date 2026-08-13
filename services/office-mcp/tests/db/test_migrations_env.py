"""Regression test for the `ConfigParser` escaping in `db/migrations/env.py`.

`env.py` runs migrations as a side effect of import (see its bottom: `run_migrations_online()`
executes unconditionally at module scope, the way every alembic `env.py` does) — so it can't be
imported directly in a unit test without a real, reachable database. Instead this extracts just
the `_configparser_escape` helper's source via the AST (the same technique `test_layering.py`
uses to inspect modules without importing them) and exercises it directly, then round-trips a
realistic percent-encoded URL through a real `alembic.config.Config` the way `env.py` itself
does.
"""

import ast
import pathlib
from collections.abc import Callable
from typing import cast

from alembic.config import Config

_ENV_PY = (
    pathlib.Path(__file__).parent.parent.parent
    / "src"
    / "office_mcp"
    / "db"
    / "migrations"
    / "env.py"
)


def _extracted_escape(value: str) -> str:
    """Run `env.py`'s `_configparser_escape` on `value`, without importing (and running) it."""
    tree = ast.parse(_ENV_PY.read_text(), filename=str(_ENV_PY))
    (function_node,) = (
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_configparser_escape"
    )
    namespace: dict[str, object] = {}
    module = ast.Module(body=[function_node], type_ignores=[])
    exec(compile(module, str(_ENV_PY), "exec"), namespace)
    escape = cast("Callable[[str], str]", namespace["_configparser_escape"])
    return escape(value)


class TestConfigparserEscape:
    def test_leaves_a_url_without_percent_signs_untouched(self) -> None:
        url = "postgresql+asyncpg://user:pass@db:5432/office"

        assert _extracted_escape(url) == url

    def test_doubles_every_percent_sign(self) -> None:
        url = "postgresql+asyncpg://user:p%40ss@db:5432/office"

        assert _extracted_escape(url) == "postgresql+asyncpg://user:p%%40ss@db:5432/office"

    def test_round_trips_a_percent_encoded_password_through_a_real_alembic_config(self) -> None:
        """The exact failure from the finding: a password containing `@`, percent-encoded by
        SQLAlchemy's `render_as_string` to `%40`, must survive `set_main_option`/
        `get_main_option` unchanged rather than raising `configparser`'s interpolation error.
        """
        url = "postgresql+asyncpg://user:p%40ss@db:5432/office"

        config = Config()
        config.set_main_option("sqlalchemy.url", _extracted_escape(url))

        assert config.get_main_option("sqlalchemy.url") == url
