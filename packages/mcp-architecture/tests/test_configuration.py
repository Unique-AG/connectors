import tomllib
from pathlib import Path

import pytest

from mcp_architecture import render_importlinter
from mcp_architecture.configuration import loosened_configuration

SHARED = (
    "[tool.ruff]\n"
    'extend = "../../packages/mcp-architecture/src/mcp_architecture/code_style.toml"\n\n'
    'target-version = "py314"\n'
    'exclude = [".venv"]\n\n'
    "[tool.ruff.lint]\n"
    'extend-select = ["FBT"]\n\n'
    "[tool.ruff.lint.per-file-ignores]\n"
    '"!src/kiosk/contexts/**" = ["PLR0917"]\n'
    '"src/kiosk/upstream/generated/vendor_responses.py" = ["N815"]\n\n'
    "[tool.basedpyright]\n"
    'extends = "../../packages/mcp-architecture/src/mcp_architecture/type_check.json"\n'
    'venvPath = "."\n'
    'venv = ".venv"\n'
    'pythonVersion = "3.14"\n'
    'include = ["src", "tests"]\n'
    "reportMissingTypeStubs = false\n"
    "reportUnusedCallResult = true\n"
    "executionEnvironments = "
    '[{ root = "tests", extraPaths = ["."], reportPrivateUsage = false }]\n\n'
)
RUFF = SHARED[: SHARED.index("[tool.basedpyright]")]
BASEDPYRIGHT = SHARED[SHARED.index("[tool.basedpyright]") :]
EXTEND_CODE_STYLE = (
    '[tool.ruff]\nextend = "../../packages/mcp-architecture/src/mcp_architecture/code_style.toml"\n'
)
EXTEND_TYPE_CHECK = (
    "[tool.basedpyright]\n"
    'extends = "../../packages/mcp-architecture/src/mcp_architecture/type_check.json"\n'
)
RESTORE = (
    "`uv run mcp-architecture-check --update` writes the table back as "
    "mcp_architecture.render_importlinter gives it, keeping the MCP's own contracts."
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
            "[tool.importlinter] dropped or changed these contracts: "
            f"['Layers only import downwards']. {RESTORE}",
        ),
        (
            ('type = "acyclic_siblings"\n', 'type = "acyclic_siblings"\nignore_imports = ["x"]\n'),
            "[tool.importlinter] dropped or changed these contracts: "
            f"['No package imports its siblings in a cycle']. {RESTORE}",
        ),
        (
            ("include_external_packages = true\n", "exclude_type_checking_imports = true\n"),
            "[tool.importlinter] changed options every MCP keeps: "
            f"['exclude_type_checking_imports', 'include_external_packages']. {RESTORE}",
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
        "[tool.importlinter] dropped or changed these contracts: "
        f"['The domain and the storage know nothing about MCP']. {RESTORE}"
    ]


def test_a_missing_importlinter_table_is_a_finding(tmp_path: Path) -> None:
    assert findings(tmp_path, SHARED) == [
        "[tool.importlinter] root_package is None, not the project's package 'kiosk', so "
        f"`lint-imports` does not check the MCP's own code. {RESTORE}"
    ]


def test_a_ruff_table_without_the_shared_code_style_is_a_finding(tmp_path: Path) -> None:
    ruff = '[tool.ruff]\ntarget-version = "py314"\n'

    assert findings(tmp_path, f"{ruff}\n{BASEDPYRIGHT}{render_importlinter('kiosk')}") == [
        "[tool.ruff] does not extend mcp_architecture/code_style.toml: add extend = "
        '"../../packages/mcp-architecture/src/mcp_architecture/code_style.toml".'
    ]


@pytest.mark.parametrize(
    ("setting", "loosened"),
    [
        ('[tool.ruff.lint]\nextend-ignore = ["ANN"]\n', "lint.extend-ignore"),
        ('[tool.ruff.lint]\nselect = ["E"]\n', "lint.select"),
        ("[tool.ruff.lint.pylint]\nmax-positional-args = 10\n", "lint.pylint"),
        ("[tool.ruff.lint.flake8-tidy-imports.banned-api]\n", "lint.flake8-tidy-imports"),
        (
            '[tool.ruff.lint]\nextend-per-file-ignores = { "**" = ["D"] }\n',
            "lint.extend-per-file-ignores",
        ),
        ('[tool.ruff]\ninclude = ["src/kiosk/main.py"]\n', "include"),
        ("[tool.ruff]\nline-length = 120\n", "line-length"),
        ('[tool.ruff]\nexclude = [".venv", "src"]\n', "exclude"),
    ],
)
def test_a_loosened_ruff_table_is_a_finding(tmp_path: Path, setting: str, loosened: str) -> None:
    ruff = EXTEND_CODE_STYLE + setting.removeprefix("[tool.ruff]\n")

    assert findings(tmp_path, f"{ruff}\n{BASEDPYRIGHT}{render_importlinter('kiosk')}") == [
        f"[tool.ruff] replaces or narrows the code style with ['{loosened}']. Remove them, and "
        "name the rule in a `# noqa: <rule>` on the line that needs it."
    ]


@pytest.mark.parametrize(
    ("path", "rules"),
    [
        ("**", '["ANN", "D"]'),
        ("src/kiosk/contexts/orders.py", '["D"]'),
        ("!src/kiosk/contexts/**", '["PLR0917", "ANN"]'),
    ],
    ids=[
        "every file",
        "a file of the MCP's own",
        "more than keyword-only arguments outside contexts",
    ],
)
def test_a_per_file_ignore_outside_generated_code_is_a_finding(
    tmp_path: Path, path: str, rules: str
) -> None:
    ruff = f'{EXTEND_CODE_STYLE}\n[tool.ruff.lint.per-file-ignores]\n"{path}" = {rules}\n'

    assert findings(tmp_path, f"{ruff}\n{BASEDPYRIGHT}{render_importlinter('kiosk')}") == [
        f"[tool.ruff.lint.per-file-ignores] turns rules off outside generated code for ['{path}']. "
        "Remove them, and name the rule in a `# noqa: <rule>` on the line that needs it. Only "
        "src/kiosk/upstream/generated/ may be listed there."
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
    basedpyright = f"{EXTEND_TYPE_CHECK}{setting}\n"

    assert findings(tmp_path, RUFF + basedpyright + render_importlinter("kiosk")) == [
        f"[tool.basedpyright] turns the type check down with ['{loosened}']. Remove them, and "
        "name the rule in a `# pyright: ignore[<rule>]` on the line that needs it."
    ]


def test_a_basedpyright_baseline_is_a_finding(tmp_path: Path) -> None:
    (tmp_path / ".basedpyright").mkdir()
    (tmp_path / ".basedpyright" / "baseline.json").write_text("{}")

    assert findings(tmp_path, SHARED + render_importlinter("kiosk")) == [
        "Remove .basedpyright/: basedpyright drops every error its baseline lists. Fix the "
        "errors instead."
    ]


@pytest.mark.parametrize(
    "path",
    [
        "pyrightconfig.json",
        ".importlinter",
        "setup.cfg",
        "ruff.toml",
        "src/kiosk/contexts/.ruff.toml",
        "src/kiosk/contexts/pyproject.toml",
    ],
)
def test_a_configuration_file_beside_pyproject_toml_is_a_finding(tmp_path: Path, path: str) -> None:
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text("")

    assert findings(tmp_path, SHARED + render_importlinter("kiosk")) == [
        f"Remove ['{path}']: each replaces a tool table of pyproject.toml."
    ]


def test_a_configuration_file_inside_the_venv_passes(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "pyproject.toml").write_text("")

    assert findings(tmp_path, SHARED + render_importlinter("kiosk")) == []
