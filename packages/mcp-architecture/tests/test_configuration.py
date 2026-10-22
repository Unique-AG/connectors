import tomllib
from pathlib import Path

import pytest

from mcp_architecture.configuration import loosened_type_check

EXTEND_TYPE_CHECK = (
    "[tool.basedpyright]\n"
    'extends = "../../packages/mcp-architecture/src/mcp_architecture/type_check.json"\n'
)
SCAFFOLDED = (
    f"{EXTEND_TYPE_CHECK}"
    'venvPath = "."\n'
    'venv = ".venv"\n'
    'pythonVersion = "3.14"\n'
    'include = ["src", "tests"]\n'
    "reportMissingTypeStubs = false\n"
    "reportUnusedCallResult = true\n"
    "executionEnvironments = "
    '[{ root = "tests", extraPaths = ["."], reportPrivateUsage = false }]\n'
)


def findings(tmp_path: Path, pyproject: str) -> list[str]:
    return loosened_type_check(tmp_path, tomllib.loads(pyproject))


def test_the_scaffolds_table_with_stricter_reports_passes(tmp_path: Path) -> None:
    assert findings(tmp_path, SCAFFOLDED) == []


@pytest.mark.parametrize(
    "extends",
    [
        "",
        'extends = "vendored/mcp_architecture/type_check.json"\n',
        'extends = "../../packages/mcp-architecture/src/mcp_architecture/../type_check.json"\n',
    ],
    ids=["missing", "a copy in the MCP", "another path"],
)
def test_a_table_that_does_not_extend_the_shared_type_check_is_a_finding(
    tmp_path: Path, extends: str
) -> None:
    assert findings(tmp_path, f"[tool.basedpyright]\n{extends}") == [
        "[tool.basedpyright] does not extend the shared type check: add extends = "
        '"../../packages/mcp-architecture/src/mcp_architecture/type_check.json".'
    ]


@pytest.mark.parametrize(
    ("setting", "loosened"),
    [
        ('typeCheckingMode = "standard"\n', "typeCheckingMode"),
        ('reportAny = "warning"\n', "reportAny"),
        ("reportPrivateUsage = false\n", "reportPrivateUsage"),
        ('ignore = ["src/kiosk/legacy"]\n', "ignore"),
        ('exclude = ["src/kiosk/legacy"]\n', "exclude"),
        ('include = ["tests"]\n', "include"),
        ("enableTypeIgnoreComments = true\n", "enableTypeIgnoreComments"),
        ("analyzeUnannotatedFunctions = false\n", "analyzeUnannotatedFunctions"),
        ("strictListInference = false\n", "strictListInference"),
        ('allowedUntypedLibraries = ["requests"]\n', "allowedUntypedLibraries"),
        ('baselineFile = "baseline.json"\n', "baselineFile"),
        (
            'executionEnvironments = [{ root = "src", reportUnknownMemberType = false }]\n',
            "reportUnknownMemberType",
        ),
        (
            'executionEnvironments = [{ root = "src", analyzeUnannotatedFunctions = false }]\n',
            "analyzeUnannotatedFunctions",
        ),
    ],
)
def test_a_loosened_basedpyright_table_is_a_finding(
    tmp_path: Path, setting: str, loosened: str
) -> None:
    assert findings(tmp_path, f"{EXTEND_TYPE_CHECK}{setting}") == [
        f"[tool.basedpyright] turns the type check down with ['{loosened}']. Remove them, and "
        "name the rule in a `# pyright: ignore[<rule>]` on the line that needs it."
    ]


def test_a_basedpyright_baseline_is_a_finding(tmp_path: Path) -> None:
    (tmp_path / ".basedpyright").mkdir()
    (tmp_path / ".basedpyright" / "baseline.json").write_text("{}")

    assert findings(tmp_path, SCAFFOLDED) == [
        "Remove .basedpyright/: basedpyright drops every error its baseline lists. Fix the "
        "errors instead."
    ]


def test_a_pyrightconfig_json_is_a_finding(tmp_path: Path) -> None:
    (tmp_path / "pyrightconfig.json").write_text("{}")

    assert findings(tmp_path, SCAFFOLDED) == [
        "Remove pyrightconfig.json: basedpyright reads it in place of [tool.basedpyright]."
    ]
