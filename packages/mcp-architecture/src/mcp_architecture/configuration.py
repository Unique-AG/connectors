"""The MCP's own tool tables in `pyproject.toml`, which may only add to what every MCP keeps."""

import json
import tomllib
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import cast

from mcp_architecture.contracts import render_importlinter

type Table = dict[str, object]

_CODE_STYLE = "mcp_architecture/code_style.toml"
_TYPE_CHECK = "mcp_architecture/type_check.json"
# The only keys an MCP's tables may set. Any other replaces, narrows or turns down a setting of the
# shared files, a sub-table such as [tool.ruff.lint.pylint] or an option such as
# basedpyright's analyzeUnannotatedFunctions alike.
_RUFF_KEYS = {"extend", "target-version", "exclude", "lint"}
_RUFF_LINT_KEYS = {"extend-select", "per-file-ignores"}
_RUFF_EXCLUDE = [".venv"]
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
# Each is read in place of a table of the MCP's pyproject.toml: ruff's in any folder, the others
# in the MCP's own.
_RUFF_CONFIGURATION = ("ruff.toml", ".ruff.toml")
_ROOT_CONFIGURATION = ("pyrightconfig.json", ".importlinter", "setup.cfg")
_NOT_THE_MCPS = {".venv", "node_modules", ".ruff_cache", ".pytest_cache"}
_RESTORE = (
    "`uv run mcp-architecture-check --update` writes the table back as "
    "mcp_architecture.render_importlinter gives it, keeping the MCP's own contracts."
)


def loosened_configuration(root: Path, pyproject: Mapping[str, object], package: str) -> list[str]:
    """Each way the MCP's ruff, basedpyright or import-linter configuration drops or loosens a rule
    of `mcp-architecture`, as a message that says how to fix it."""
    tool = cast(dict[str, Table], pyproject.get("tool", {}))
    return [
        *_other_configuration_findings(root),
        *_importlinter_findings(tool.get("importlinter", {}), package),
        *_ruff_findings(tool.get("ruff", {}), package),
        *_basedpyright_findings(tool.get("basedpyright", {})),
    ]


def _other_configuration_findings(root: Path) -> list[str]:
    found = [
        str(path.relative_to(root))
        for path in sorted(root.rglob("*"))
        if not _NOT_THE_MCPS.intersection(path.relative_to(root).parts)
        and _replaces_a_table(path, in_root=path.parent == root)
    ]
    findings = [f"Remove {found}: each replaces a tool table of pyproject.toml."] if found else []
    if (root / _PYRIGHT_BASELINE).exists():
        findings.append(
            f"Remove {_PYRIGHT_BASELINE}/: basedpyright drops every error its baseline lists. Fix "
            "the errors instead."
        )
    return findings


def _replaces_a_table(path: Path, *, in_root: bool) -> bool:
    """A nested pyproject.toml with a `[tool.ruff]` table is a ruff configuration too."""
    if in_root:
        return path.name in (*_RUFF_CONFIGURATION, *_ROOT_CONFIGURATION)
    return path.name in (*_RUFF_CONFIGURATION, "pyproject.toml")


def _importlinter_findings(table: Table, package: str) -> list[str]:
    rendered = cast(
        Table, cast(Table, tomllib.loads(render_importlinter(package))["tool"])["importlinter"]
    )
    if table.get("root_package") != package:
        return [
            f"[tool.importlinter] root_package is {table.get('root_package')!r}, not the "
            f"project's package {package!r}, so `lint-imports` does not check the MCP's own code. "
            f"{_RESTORE}"
        ]
    findings: list[str] = []
    contracts = cast(list[Table], table.get("contracts", []))
    missing = [
        str(contract["name"])
        for contract in cast(list[Table], rendered["contracts"])
        if contract not in contracts
    ]
    if missing:
        findings.append(
            f"[tool.importlinter] dropped or changed these contracts: {missing}. {_RESTORE}"
        )
    types = cast(list[str], table.get("contract_types", []))
    options = {key: value for key, value in table.items() if key != "contracts"}
    expected = {key: value for key, value in rendered.items() if key != "contracts"}
    changed = sorted(
        key
        for key in options.keys() | expected.keys()
        if key != "contract_types" and options.get(key) != expected.get(key)
    )
    if changed or not set(cast(list[str], rendered["contract_types"])) <= set(types):
        findings.append(
            "[tool.importlinter] changed options every MCP keeps: "
            f"{changed or ['contract_types']}. {_RESTORE}"
        )
    return findings


def _ruff_findings(table: Table, package: str) -> list[str]:
    findings: list[str] = []
    if not str(table.get("extend", "")).endswith(_CODE_STYLE):
        findings.append(
            f'[tool.ruff] does not extend {_CODE_STYLE}: add extend = "../../packages/'
            f'mcp-architecture/src/{_CODE_STYLE}".'
        )
    lint = cast(Table, table.get("lint", {}))
    loosened = sorted(
        [key for key in table if key not in _RUFF_KEYS]
        + [f"lint.{key}" for key in lint if key not in _RUFF_LINT_KEYS]
        + (["exclude"] if table.get("exclude", _RUFF_EXCLUDE) != _RUFF_EXCLUDE else [])
    )
    if loosened:
        findings.append(
            f"[tool.ruff] replaces or narrows the code style with {loosened}. Remove them, and "
            "name the rule in a `# noqa: <rule>` on the line that needs it."
        )
    per_file = cast(dict[str, list[str]], lint.get("per-file-ignores", {}))
    if ignored := [
        path for path, rules in per_file.items() if not _generated(path, rules, package)
    ]:
        findings.append(
            f"[tool.ruff.lint.per-file-ignores] turns rules off outside generated code for "
            f"{ignored}. Remove them, and name the rule in a `# noqa: <rule>` on the line that "
            f"needs it. Only src/{package}/upstream/generated/ may be listed there."
        )
    return findings


def _generated(path: str, rules: list[str], package: str) -> bool:
    """Generated code, or the entry that limits keyword-only arguments to `contexts/`."""
    if path == f"!src/{package}/contexts/**":
        return rules == ["PLR0917"]
    return path.startswith(f"src/{package}/upstream/generated/")


def _basedpyright_findings(table: Table) -> list[str]:
    findings: list[str] = []
    if not str(table.get("extends", "")).endswith(_TYPE_CHECK):
        findings.append(
            f'[tool.basedpyright] does not extend {_TYPE_CHECK}: add extends = "../../packages/'
            f'mcp-architecture/src/{_TYPE_CHECK}".'
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
