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
# Each replaces or narrows the rules code_style.toml selects. per-file-ignores is left to review,
# since generated code needs it.
_RUFF_LOOSENING = ("select", "ignore", "extend-ignore")
# Each turns basedpyright's `all` mode down for the whole MCP or for some of its files.
_PYRIGHT_LOOSENING = ("typeCheckingMode", "ignore", "exclude", "enableTypeIgnoreComments")
_STRICT_VALUES = (True, "error")


def loosened_configuration(root: Path, pyproject: Mapping[str, object], package: str) -> list[str]:
    """Each way the MCP's ruff, basedpyright or import-linter table drops or loosens a rule of
    `mcp-architecture`, as a message that says how to fix it."""
    tool = cast(dict[str, Table], pyproject.get("tool", {}))
    return [
        *_importlinter_findings(tool.get("importlinter", {}), package),
        *_ruff_findings(tool.get("ruff", {})),
        *_basedpyright_findings(root, tool.get("basedpyright", {})),
    ]


def _importlinter_findings(table: Table, package: str) -> list[str]:
    rendered = cast(
        Table, cast(Table, tomllib.loads(render_importlinter(package))["tool"])["importlinter"]
    )
    if table.get("root_package") != package:
        return [
            f"[tool.importlinter] root_package is {table.get('root_package')!r}, not the "
            f"project's package {package!r}, so `lint-imports` does not check the MCP's own code."
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
            "[tool.importlinter] dropped or changed these contracts. Restore them as "
            f"mcp_architecture.render_importlinter writes them: {missing}"
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
            "[tool.importlinter] changed options every MCP keeps. Restore them as "
            f"mcp_architecture.render_importlinter writes them: {changed or ['contract_types']}"
        )
    return findings


def _ruff_findings(table: Table) -> list[str]:
    findings: list[str] = []
    if not str(table.get("extend", "")).endswith(_CODE_STYLE):
        findings.append(
            f'[tool.ruff] does not extend {_CODE_STYLE}: add extend = "../../packages/'
            f'mcp-architecture/src/{_CODE_STYLE}".'
        )
    lint = cast(Table, table.get("lint", {}))
    if loosened := [key for key in _RUFF_LOOSENING if key in table or key in lint]:
        findings.append(
            f"[tool.ruff] replaces or narrows the code style with {loosened}. Remove them, and "
            "name the rule in a `# noqa: <rule>` on the line that needs it."
        )
    return findings


def _basedpyright_findings(root: Path, table: Table) -> list[str]:
    findings: list[str] = []
    if (root / "pyrightconfig.json").is_file():
        findings.append("Remove pyrightconfig.json: it replaces [tool.basedpyright].")
    if not str(table.get("extends", "")).endswith(_TYPE_CHECK):
        findings.append(
            f'[tool.basedpyright] does not extend {_TYPE_CHECK}: add extends = "../../packages/'
            f'mcp-architecture/src/{_TYPE_CHECK}".'
        )
    shared = cast(
        Table, json.loads(files("mcp_architecture").joinpath("type_check.json").read_text())
    )
    environments = cast(list[Table], table.get("executionEnvironments", []))
    loosened = [key for key in _PYRIGHT_LOOSENING if key in table] + [
        key
        for settings in [table, *environments]
        for key, value in settings.items()
        if key.startswith("report")
        and value not in _STRICT_VALUES
        and value != shared.get(key)
        and not _is_tests_private_usage(settings, key)
    ]
    if loosened:
        findings.append(
            f"[tool.basedpyright] turns the type check down with {sorted(set(loosened))}. Remove "
            "them, and name the rule in a `# pyright: ignore[<rule>]` on the line that needs it."
        )
    return findings


def _is_tests_private_usage(settings: Table, key: str) -> bool:
    """A test may reach a private name of the code it tests, as ARCHITECTURE.md allows."""
    return key == "reportPrivateUsage" and settings.get("root") == "tests"
