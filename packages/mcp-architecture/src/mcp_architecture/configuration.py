"""The MCP's `[tool.basedpyright]`, which may only add to the shared type check. ruff and
import-linter need no such check: `mcp-architecture-lint` and `mcp-architecture-imports` pass them
the shared configuration, whatever the MCP's own says."""

import json
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import cast

type Table = dict[str, object]

_TYPE_CHECK = "../../packages/mcp-architecture/src/mcp_architecture/type_check.json"
# The only keys the table may set. Any other turns the check down, an option such as
# analyzeUnannotatedFunctions or baselineFile alike.
_PYRIGHT_KEYS = {
    "extends",
    "venvPath",
    "venv",
    "pythonVersion",
    "include",
    "strict",
    "executionEnvironments",
}
_ENVIRONMENT_KEYS = {"root", "extraPaths", "pythonVersion"}
_PYRIGHT_INCLUDE = ["src", "tests"]
_STRICT_VALUES = (True, "error")
# basedpyright reads it without being told, and drops every error it lists.
_PYRIGHT_BASELINE = ".basedpyright"
# basedpyright reads it in place of [tool.basedpyright].
_PYRIGHT_CONFIGURATION = "pyrightconfig.json"


def loosened_type_check(root: Path, pyproject: Mapping[str, object]) -> list[str]:
    """Each way the MCP's basedpyright configuration drops or loosens the shared type check, as a
    message that says how to fix it."""
    tool = cast(dict[str, Table], pyproject.get("tool", {}))
    findings = _basedpyright_findings(tool.get("basedpyright", {}))
    if (root / _PYRIGHT_CONFIGURATION).exists():
        findings.append(
            f"Remove {_PYRIGHT_CONFIGURATION}: basedpyright reads it in place of "
            "[tool.basedpyright]."
        )
    if (root / _PYRIGHT_BASELINE).exists():
        findings.append(
            f"Remove {_PYRIGHT_BASELINE}/: basedpyright drops every error its baseline lists. Fix "
            "the errors instead."
        )
    return findings


def _basedpyright_findings(table: Table) -> list[str]:
    findings: list[str] = []
    if table.get("extends") != _TYPE_CHECK:
        findings.append(
            "[tool.basedpyright] does not extend the shared type check: add "
            f'extends = "{_TYPE_CHECK}".'
        )
    shared = cast(
        Table, json.loads(files("mcp_architecture").joinpath("type_check.json").read_text())
    )
    environments = cast(list[Table], table.get("executionEnvironments", []))
    narrowed = ["include"] if table.get("include", _PYRIGHT_INCLUDE) != _PYRIGHT_INCLUDE else []
    loosened = (
        narrowed
        + [key for key in table if key not in _PYRIGHT_KEYS and not key.startswith("report")]
        + [
            key
            for environment in environments
            for key in environment
            if key not in _ENVIRONMENT_KEYS and not key.startswith("report")
        ]
        + [
            key
            for settings in [table, *environments]
            for key, value in settings.items()
            if key.startswith("report")
            and value not in _STRICT_VALUES
            and value != shared.get(key)
            and not _is_tests_private_usage(settings, key)
        ]
    )
    if loosened:
        findings.append(
            f"[tool.basedpyright] turns the type check down with {sorted(set(loosened))}. Remove "
            "them, and name the rule in a `# pyright: ignore[<rule>]` on the line that needs it."
        )
    return findings


def _is_tests_private_usage(settings: Table, key: str) -> bool:
    """A test may reach a private name of the code it tests, as ARCHITECTURE.md allows."""
    return key == "reportPrivateUsage" and settings.get("root") == "tests"
