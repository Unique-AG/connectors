import subprocess
from pathlib import Path

import pytest

from mcp_architecture.lint import CODE_STYLE, lint

SCAFFOLDED = (
    '[project]\nname = "shop"\n\n'
    f'[tool.ruff]\nextend = "{CODE_STYLE}"\n\n'
    "[tool.ruff.lint.per-file-ignores]\n"
    '"!**/src/*/contexts/**" = ["PLR0917"]\n'
    '"**/src/*/upstream/generated/**" = ["N815"]\n'
)
CLEAN = '"""Notes."""\n\nNOTE = "kept"\n'
PRINTS = 'print("kept")\n'
OPTIONAL = "from typing import Optional\n\nLIMIT: Optional[int] = None\n"


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    """An MCP whose [tool.ruff] is the one the scaffold writes, with one clean module."""
    (tmp_path / "pyproject.toml").write_text(SCAFFOLDED)
    write(tmp_path, "src/shop/__init__.py", "")
    write(tmp_path, "src/shop/telemetry/__init__.py", "")
    write(tmp_path, "src/shop/telemetry/notes.py", CLEAN)
    return tmp_path


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_an_mcp_that_keeps_the_code_style_passes(
    shop: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    assert lint(shop) == 0
    assert "miss" not in capfd.readouterr().out


LOOSENED = {
    "a rule ignored": {
        "pyproject.toml": f'{SCAFFOLDED}[tool.ruff.lint]\nextend-ignore = ["T20"]\n'
    },
    "the rules replaced": {"pyproject.toml": f'{SCAFFOLDED}[tool.ruff.lint]\nselect = ["E9"]\n'},
    "a per-file ignore with ..": {
        "pyproject.toml": (
            f'{SCAFFOLDED}"src/shop/upstream/generated/../../telemetry/**" = ["T201"]\n'
        )
    },
    "a loosened copy extended": {
        "pyproject.toml": SCAFFOLDED.replace(CODE_STYLE, "vendored/code_style.toml"),
        "vendored/code_style.toml": '[lint]\nselect = ["E9"]\n',
    },
    "a nested ruff.toml": {"src/shop/telemetry/ruff.toml": '[lint]\nselect = ["E9"]\n'},
}


@pytest.mark.parametrize("files", LOOSENED.values(), ids=LOOSENED.keys())
def test_the_mcps_own_configuration_does_not_loosen_the_code_style(
    shop: Path, capfd: pytest.CaptureFixture[str], files: dict[str, str]
) -> None:
    write(shop, "src/shop/telemetry/notes.py", PRINTS)
    for relative, text in files.items():
        write(shop, relative, text)

    assert lint(shop) == 1
    output = capfd.readouterr().out
    assert "T201" in output
    assert "The MCP's editor and a bare `ruff check` miss ['T201']" in output


def test_an_older_target_version_does_not_loosen_the_code_style(
    shop: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    write(shop, "src/shop/telemetry/notes.py", OPTIONAL)
    (shop / "pyproject.toml").write_text(
        SCAFFOLDED.replace("[tool.ruff]\n", '[tool.ruff]\ntarget-version = "py38"\n')
    )

    assert lint(shop) == 1
    assert "miss ['UP045']" in capfd.readouterr().out


@pytest.mark.parametrize(
    ("ignore", "git"),
    [(".ignore", False), ("src/shop/telemetry/.gitignore", True)],
    ids=["an .ignore", "a .gitignore matching a committed file"],
)
def test_a_file_an_ignore_file_lists_is_still_checked(
    shop: Path, capfd: pytest.CaptureFixture[str], ignore: str, git: bool
) -> None:
    if git:
        subprocess.run(["git", "init", "-q"], cwd=shop, check=True)
    write(shop, "src/shop/telemetry/notes.py", PRINTS)
    write(shop, ignore, "notes.py\n")

    assert lint(shop) == 1
    assert "src/shop/telemetry/notes.py:1:1" in capfd.readouterr().out


def test_a_rule_the_mcp_adds_is_checked_too(shop: Path, capfd: pytest.CaptureFixture[str]) -> None:
    write(shop, "pyproject.toml", f'{SCAFFOLDED}[tool.ruff.lint]\nextend-select = ["FBT"]\n')
    write(
        shop,
        "src/shop/telemetry/flags.py",
        "def on(flag: bool = False) -> bool:\n    return flag\n",
    )

    assert lint(shop) == 1
    output = capfd.readouterr().out
    assert "Rules the MCP's [tool.ruff] adds find:" in output
    assert "src/shop/telemetry/flags.py:1:8: FBT001" in output


def test_unformatted_code_fails_until_fixed(shop: Path) -> None:
    write(shop, "src/shop/telemetry/notes.py", "NOTE   =   'kept'\n")

    assert lint(shop) == 1
    assert lint(shop, fix=True) == 0
    assert (shop / "src/shop/telemetry/notes.py").read_text() == 'NOTE = "kept"\n'


def test_an_unreadable_configuration_of_the_mcps_own_fails(shop: Path) -> None:
    (shop / "pyproject.toml").write_text(SCAFFOLDED.replace(CODE_STYLE, "missing.toml"))

    assert lint(shop) == 1
