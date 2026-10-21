import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_scaffold.cli import main
from tests.conftest import REGISTRIES, REPO

VALID_ARGUMENTS = [
    "--description",
    "Probes.",
    "--upstream",
    "custom",
    "--persistence",
    "none",
]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A clean git repository with the registries, a shared package and a non-service scope."""
    for registry in REGISTRIES:
        (tmp_path / registry).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / registry, tmp_path / registry)
    gitcommitizen = tmp_path / ".gitcommitizen"
    gitcommitizen.write_text(
        gitcommitizen.read_text().replace("# Docs\n", "# Docs\nguides-mcp = docs/guides-mcp/**\n")
    )
    (tmp_path / "packages" / "shared-mcp").mkdir(parents=True)
    (tmp_path / "packages" / "shared-mcp" / "pyproject.toml").write_text("")
    (tmp_path / "services" / "taken-mcp").mkdir(parents=True)
    (tmp_path / "services" / "taken-mcp" / "pyproject.toml").write_text("")
    settings = [
        "user.name=Probe",
        "user.email=probe@example.com",
        "commit.gpgsign=false",
        "core.hooksPath=/dev/null",
    ]
    git = ["git", *(option for setting in settings for option in ("-c", setting))]
    for command in [["init", "-q"], ["add", "."], ["commit", "-q", "-m", "init"]]:
        subprocess.run([*git, *command], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def refusal(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    monkeypatch.setattr(sys, "argv", ["mcp-scaffold", "new", *argv])

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 2
    return capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("weather", "name: must be kebab-case and end in -mcp"),
        ("Weather-mcp", "name: must be kebab-case and end in -mcp"),
        ("weather--mcp", "name: must be kebab-case and end in -mcp"),
        ("unique-mcp", "unique-mcp would shadow the package of that name"),
        ("shared-mcp", "shared-mcp would shadow the package of that name"),
        ("guides-mcp", "guides-mcp is already the commit scope of docs/guides-mcp/**"),
        ("taken-mcp", "services/taken-mcp already exists"),
    ],
)
@pytest.mark.usefixtures("repo")
def test_a_name_that_cannot_be_a_service_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str, message: str
) -> None:
    assert message in refusal(monkeypatch, capsys, name, *VALID_ARGUMENTS)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            ["--persistence", "none", "redis"],
            "--persistence none cannot be combined with a store",
        ),
        (["--spec", "weather.json"], "--spec goes with --upstream openapi, and only it"),
    ],
    ids=["none with a store", "a spec with a custom upstream"],
)
@pytest.mark.usefixtures("repo")
def test_options_that_contradict_each_other_are_refused(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    message: str,
) -> None:
    assert message in refusal(monkeypatch, capsys, "weather-mcp", *VALID_ARGUMENTS, *arguments)


@pytest.mark.usefixtures("repo")
def test_a_spec_without_an_upstream_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["--description", "Probes.", "--persistence", "none", "--spec", "weather.json"]

    error = refusal(monkeypatch, capsys, "weather-mcp", *arguments)

    assert "--spec goes with --upstream openapi, and only it" in error


def test_an_untracked_file_refuses_the_run_whatever_git_is_told_to_show(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "config", "status.showUntrackedFiles", "no"], cwd=repo, check=True)
    (repo / "notes" / "draft.md").parent.mkdir()
    (repo / "notes" / "draft.md").write_text("draft")

    error = refusal(monkeypatch, capsys, "weather-mcp", *VALID_ARGUMENTS)

    assert "commit or stash every change first" in error
    assert "?? notes/draft.md" in error
    assert not (repo / "services" / "weather-mcp").exists()


def test_a_run_outside_the_repository_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    error = refusal(monkeypatch, capsys, "weather-mcp", *VALID_ARGUMENTS)

    assert "run mcp-scaffold from the repository root" in error
