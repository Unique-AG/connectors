import tomllib
from pathlib import Path

import pytest

from mcp_architecture import render_importlinter
from mcp_architecture.configuration import loosened_configuration

SHARED = (
    "[tool.ruff]\n"
    'extend = "../../packages/mcp-architecture/src/mcp_architecture/code_style.toml"\n\n'
    "[tool.ruff.lint.per-file-ignores]\n"
    '"src/kiosk/upstream/generated/vendor_responses.py" = ["N815"]\n\n'
    "[tool.basedpyright]\n"
    'extends = "../../packages/mcp-architecture/src/mcp_architecture/type_check.json"\n'
    "reportMissingTypeStubs = false\n"
    "reportUnusedCallResult = true\n"
    'executionEnvironments = [{ root = "tests", reportPrivateUsage = false }]\n\n'
)
OWN_CONTRACT = (
    "\n[[tool.importlinter.contracts]]\n"
    'name = "Orders know nothing about payments"\n'
    'type = "forbidden"\n'
    'source_modules = ["kiosk.contexts.orders"]\n'
    'forbidden_modules = ["kiosk.contexts.payments"]\n'
)


def findings(tmp_path: Path, pyproject: str) -> list[str]:
    return loosened_configuration(tmp_path, tomllib.loads(pyproject), "kiosk")


def test_the_scaffolds_tables_with_additions_of_their_own_pass(tmp_path: Path) -> None:
    assert findings(tmp_path, SHARED + render_importlinter("kiosk") + OWN_CONTRACT) == []


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (
            ("exhaustive = true\n", "exhaustive = false\n"),
            "[tool.importlinter] dropped or changed these contracts. Restore them as "
            "mcp_architecture.render_importlinter writes them: ['Layers only import downwards']",
        ),
        (
            ('type = "acyclic_siblings"\n', 'type = "acyclic_siblings"\nignore_imports = ["x"]\n'),
            "[tool.importlinter] dropped or changed these contracts. Restore them as "
            "mcp_architecture.render_importlinter writes them: "
            "['No package imports its siblings in a cycle']",
        ),
        (
            ("include_external_packages = true\n", "exclude_type_checking_imports = true\n"),
            "[tool.importlinter] changed options every MCP keeps. Restore them as "
            "mcp_architecture.render_importlinter writes them: "
            "['exclude_type_checking_imports', 'include_external_packages']",
        ),
    ],
    ids=["a loosened contract", "an ignored import", "a changed option"],
)
def test_a_loosened_importlinter_table_is_a_finding(
    tmp_path: Path, edit: tuple[str, str], expected: str
) -> None:
    importlinter = render_importlinter("kiosk").replace(*edit, 1)

    assert findings(tmp_path, SHARED + importlinter) == [expected]


def test_a_dropped_contract_is_a_finding(tmp_path: Path) -> None:
    rendered = render_importlinter("kiosk")
    without_last = rendered[: rendered.rindex("\n[[tool.importlinter.contracts]]")] + "\n"

    assert findings(tmp_path, SHARED + without_last) == [
        "[tool.importlinter] dropped or changed these contracts. Restore them as "
        "mcp_architecture.render_importlinter writes them: "
        "['The domain and the storage know nothing about MCP']"
    ]


def test_a_missing_importlinter_table_is_a_finding(tmp_path: Path) -> None:
    assert findings(tmp_path, SHARED) == [
        "[tool.importlinter] root_package is None, not the project's package 'kiosk', so "
        "`lint-imports` does not check the MCP's own code."
    ]


@pytest.mark.parametrize(
    ("ruff", "expected"),
    [
        (
            "[tool.ruff]\nline-length = 120\n",
            "[tool.ruff] does not extend mcp_architecture/code_style.toml: add extend = "
            '"../../packages/mcp-architecture/src/mcp_architecture/code_style.toml".',
        ),
        (
            '[tool.ruff]\nextend = "../../packages/mcp-architecture/src/mcp_architecture/'
            'code_style.toml"\n\n[tool.ruff.lint]\nextend-ignore = ["ANN"]\n',
            "[tool.ruff] replaces or narrows the code style with ['extend-ignore']. Remove "
            "them, and name the rule in a `# noqa: <rule>` on the line that needs it.",
        ),
    ],
    ids=["no extend", "an ignored rule"],
)
def test_a_loosened_ruff_table_is_a_finding(tmp_path: Path, ruff: str, expected: str) -> None:
    basedpyright = SHARED[SHARED.index("[tool.basedpyright]") :]

    assert findings(tmp_path, f"{ruff}\n{basedpyright}{render_importlinter('kiosk')}") == [expected]


@pytest.mark.parametrize(
    ("setting", "loosened"),
    [
        ('typeCheckingMode = "standard"\n', "typeCheckingMode"),
        ('reportAny = "warning"\n', "reportAny"),
        ("reportPrivateUsage = false\n", "reportPrivateUsage"),
        ('ignore = ["src/kiosk/legacy"]\n', "ignore"),
        (
            'executionEnvironments = [{ root = "src", reportUnknownMemberType = false }]\n',
            "reportUnknownMemberType",
        ),
    ],
)
def test_a_loosened_basedpyright_table_is_a_finding(
    tmp_path: Path, setting: str, loosened: str
) -> None:
    basedpyright = (
        "[tool.basedpyright]\n"
        'extends = "../../packages/mcp-architecture/src/mcp_architecture/type_check.json"\n'
        f"{setting}\n"
    )
    ruff = SHARED[: SHARED.index("[tool.basedpyright]")]

    assert findings(tmp_path, ruff + basedpyright + render_importlinter("kiosk")) == [
        f"[tool.basedpyright] turns the type check down with ['{loosened}']. Remove them, and "
        "name the rule in a `# pyright: ignore[<rule>]` on the line that needs it."
    ]


def test_a_pyrightconfig_json_is_a_finding(tmp_path: Path) -> None:
    (tmp_path / "pyrightconfig.json").write_text("{}")

    assert findings(tmp_path, SHARED + render_importlinter("kiosk")) == [
        "Remove pyrightconfig.json: it replaces [tool.basedpyright]."
    ]
