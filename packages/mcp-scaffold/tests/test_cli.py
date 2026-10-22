import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from mcp_scaffold import cli, commands
from mcp_scaffold.cli import main
from tests.conftest import REGISTRIES, REPO, UseVenv, copy_registries, run_linked

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
    """A clean git repository with the registries, the shared packages, a package named like an
    MCP and a non-service scope."""
    copy_registries(tmp_path)
    gitcommitizen = tmp_path / ".gitcommitizen"
    gitcommitizen.write_text(
        gitcommitizen.read_text().replace("# Docs\n", "# Docs\nguides-mcp = docs/guides-mcp/**\n")
    )
    (tmp_path / "packages").mkdir()
    for package in (REPO / "packages").iterdir():
        if package.is_dir():
            (tmp_path / "packages" / package.name).symlink_to(package.resolve())
    (tmp_path / "packages" / "shared-mcp").mkdir()
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


def read_registries(repo: Path) -> dict[str, str]:
    return {registry: (repo / registry).read_text() for registry in REGISTRIES}


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
        ("taken-mcp", "`git clean -fdx services/taken-mcp` removes"),
        (f"{'a' * 30}-mcp", "name: must be at most 33 characters"),
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


def test_a_run_outside_a_git_repository_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    copy_registries(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)

    error = refusal(monkeypatch, capsys, "weather-mcp", *VALID_ARGUMENTS)

    assert "git cannot tell whether the tree is clean" in error
    assert not (tmp_path / "services" / "weather-mcp").exists()


@pytest.mark.usefixtures("repo")
def test_a_run_without_git_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", "")

    error = refusal(monkeypatch, capsys, "weather-mcp", *VALID_ARGUMENTS)

    assert "git is not installed" in error


@pytest.mark.parametrize(
    ("spec", "content"),
    [
        ("missing.yml", None),
        ("http://127.0.0.1:9/openapi.yml", None),
        ("newer.yml", "openapi: 3.1.0\npaths: {}\n"),
        ("broken.yml", "openapi: [\n"),
    ],
    ids=["a missing file", "an unreachable URL", "OpenAPI 3.1", "not YAML"],
)
def test_a_spec_the_scaffold_cannot_use_is_refused_before_anything_is_written(
    repo: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    spec: str,
    content: str | None,
) -> None:
    if content is not None:
        outside = tmp_path_factory.mktemp("specs") / spec
        outside.write_text(content)
        spec = str(outside)
    arguments = ["--description", "Probes.", "--upstream", "openapi", "--persistence", "none"]

    error = refusal(monkeypatch, capsys, "weather-mcp", *arguments, "--spec", spec)

    assert f"cannot use the spec {spec}: " in error
    assert not (repo / "services" / "weather-mcp").exists()


def test_a_description_with_a_newline_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    arguments = ["--description", "Two\nlines.", "--persistence", "none"]

    error = refusal(monkeypatch, capsys, "weather-mcp", *arguments)

    assert "description: must be one line" in error
    assert not (repo / "services" / "weather-mcp").exists()


@pytest.mark.parametrize(
    "registry", ["release-please-config.json", ".release-please-manifest.json"]
)
def test_a_name_a_removed_service_still_releases_under_is_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], registry: str
) -> None:
    entries = cast(dict[str, object], json.loads((repo / registry).read_text()))
    releases = cast(dict[str, object], entries["packages"]) if "packages" in entries else entries
    releases["services/weather-mcp"] = "1.2.0"
    (repo / registry).write_text(json.dumps(entries))

    error = refusal(monkeypatch, capsys, "weather-mcp", *VALID_ARGUMENTS)

    assert f"services/weather-mcp still has a release entry in {registry}," in error


def test_an_untracked_spec_in_the_repository_is_named_in_the_refusal(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "weather.yml").write_text("openapi: 3.0.3\n")
    arguments = ["--description", "Probes.", "--upstream", "openapi", "--persistence", "none"]

    error = refusal(monkeypatch, capsys, "weather-mcp", *arguments, "--spec", "weather.yml")

    assert "?? weather.yml" in error
    assert "commit it, or pass a --spec path outside the repository" in error


def test_a_dirty_tree_without_the_spec_in_it_gives_no_spec_hint(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "notes.md").write_text("draft")

    error = refusal(monkeypatch, capsys, "weather-mcp", *VALID_ARGUMENTS)

    assert "?? notes.md" in error
    assert "--spec path outside" not in error


@pytest.mark.usefixtures("repo")
def test_a_failed_check_prints_how_to_undo_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_scaffold(*_arguments: object, **_options: object) -> Path:
        raise subprocess.CalledProcessError(1, ["uv", "run", "pytest", "-q"])

    monkeypatch.setattr(cli, "scaffold", failing_scaffold)
    monkeypatch.setattr(sys, "argv", ["mcp-scaffold", "new", "weather-mcp", *VALID_ARGUMENTS])

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == (
        "`uv run pytest -q` failed in services/weather-mcp, as printed above. Undo the run from "
        "the repository root:\n  git checkout . && git clean -fdx services/weather-mcp"
    )


@pytest.mark.usefixtures("repo")
def test_any_other_failure_prints_how_to_undo_the_run_and_is_raised(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_scaffold(*_arguments: object, **_options: object) -> Path:
        raise AssertionError("pnpm-workspace.yaml excludes no Python service")

    monkeypatch.setattr(cli, "scaffold", failing_scaffold)
    monkeypatch.setattr(sys, "argv", ["mcp-scaffold", "new", "weather-mcp", *VALID_ARGUMENTS])

    with pytest.raises(AssertionError, match="excludes no Python service"):
        main()

    assert capsys.readouterr().err == (
        "The run stopped in services/weather-mcp, as printed below. Undo the run from the "
        "repository root:\n  git checkout . && git clean -fdx services/weather-mcp\n"
    )


def test_a_run_without_a_release_registers_the_mcp_but_no_release(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    use_venv: UseVenv,
) -> None:
    releases = [
        "release-please-config.json",
        ".release-please-manifest.json",
        ".github/workflows/release-rerun.yaml",
    ]
    before = read_registries(repo)
    use_venv("probe-cli-mcp")
    monkeypatch.setattr(commands, "run", run_linked)
    monkeypatch.setattr(
        sys, "argv", ["mcp-scaffold", "new", "probe-cli-mcp", *VALID_ARGUMENTS, "--no-release"]
    )

    main()

    after = read_registries(repo)
    assert "services/probe-cli-mcp is ready." in capsys.readouterr().out
    assert {registry: after[registry] for registry in releases} == {
        registry: before[registry] for registry in releases
    }
    assert "probe-cli-mcp = services/probe-cli-mcp/**" in after[".gitcommitizen"]
    assert '"!services/probe-cli-mcp"' in after["pnpm-workspace.yaml"]
    head = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    pyproject = (repo / "services" / "probe-cli-mcp" / "pyproject.toml").read_text()
    assert pyproject.startswith(f"# mcp-scaffold-commit: {head}, timestamp: ")
