"""Generate a Python MCP, once. From the repository root, though it finds the root itself:

uv run --project packages/mcp-scaffold mcp-scaffold <name> \\
    --description "<what it does>" [--upstream openapi|custom] [--spec <path or URL>] \\
    [--persistence postgres|redis [postgres|redis]] [--auth credentials]

The `new-mcp` skill asks for the options and runs it. The MCP owns every file it generates.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import cast

import yaml
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from mcp_scaffold.options import Auth, Options, Persistence, Upstream
from mcp_scaffold.repository import name_conflict
from mcp_scaffold.scaffold import load_spec, scaffold


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-scaffold", description=(__doc__ or "").split("\n\n")[0]
    )
    parser.add_argument("name", help="kebab-case, e.g. weather-mcp")
    parser.add_argument("--description", required=True)
    parser.add_argument(
        "--upstream",
        type=Upstream,
        choices=list(Upstream),
        help="what the MCP calls; leave it out for an MCP without an upstream client",
    )
    parser.add_argument(
        "--spec",
        help="the vendor's OpenAPI 3.0 spec, a path or an http(s) URL; --upstream openapi needs it",
    )
    parser.add_argument(
        "--persistence",
        nargs="+",
        type=Persistence,
        choices=list(Persistence),
        default=[],
        help="every store the MCP owns, e.g. --persistence postgres redis; leave it out for none",
    )
    parser.add_argument(
        "--auth",
        type=Auth,
        choices=list(Auth),
        help="how users sign in; leave it out for an MCP that starts without sign-in",
    )
    parser.add_argument(
        "--no-release",
        dest="release",
        action="store_false",
        help="skip release-please and the release re-run list",
    )
    arguments = parser.parse_args()

    repo = _repository(parser)
    try:
        options = Options.model_validate(vars(arguments))
    except ValidationError as error:
        parser.error("\n".join(_describe(problem) for problem in error.errors()))
    if (conflict := name_conflict(options.name, repo)) is not None:
        parser.error(conflict)
    _require_clean(parser, repo, options.spec)
    commit = _head_commit(parser, repo)
    try:
        spec = load_spec(options, repo)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(f"cannot use the spec {options.spec}: {error}")
    undo = (
        "Undo the run from the repository root:\n"
        f"  git checkout . && git clean -fdx services/{options.name}"
    )
    try:
        target = scaffold(
            options, repo, spec=spec, commit=commit, release=cast(bool, arguments.release)
        )
    except subprocess.CalledProcessError as error:
        command = " ".join(cast(list[str], error.cmd))
        sys.exit(f"`{command}` failed in services/{options.name}, as printed above. {undo}")
    except BaseException:
        print(
            f"The run stopped in services/{options.name}, as printed below. {undo}", file=sys.stderr
        )
        raise
    print(f"{target} is ready. The new-mcp skill lists what to fill in next.")


def _repository(parser: argparse.ArgumentParser) -> Path:
    """The root of the repository the command runs in, from any folder of it."""
    try:
        root = Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except FileNotFoundError:
        parser.error("git is not installed, and the run needs it to find the repository")
    except subprocess.CalledProcessError as error:
        parser.error(f"run mcp-scaffold inside the repository: {cast(str, error.stderr).strip()}")
    if not (root / ".gitcommitizen").is_file():
        parser.error(f"run mcp-scaffold inside the connectors repository, not {root}")
    return root


def _require_clean(parser: argparse.ArgumentParser, repo: Path, spec: str | None) -> None:
    try:
        changes = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except FileNotFoundError:
        parser.error("git is not installed, and the run needs it to check the tree is clean")
    except subprocess.CalledProcessError as error:
        parser.error(
            f"git cannot tell whether the tree is clean: {cast(str, error.stderr).strip()}"
        )
    if changes:
        parser.error(
            "commit or stash every change first, untracked files too, so git alone can undo "
            f"the run:\n{changes}{_untracked_spec_hint(repo, spec, changes)}"
        )


def _head_commit(parser: argparse.ArgumentParser, repo: Path) -> str:
    """The commit every file the run writes is stamped with, short enough for the stamp to fit
    in a line. The tree is clean, so it is exact."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as error:
        parser.error(
            f"git has no commit to stamp the files with: {cast(str, error.stderr).strip()}"
        )


def _untracked_spec_hint(repo: Path, spec: str | None, changes: str) -> str:
    if spec is None or spec.startswith(("http://", "https://")):
        return ""
    root = repo.resolve()
    path = (repo / spec).resolve()
    if not path.is_relative_to(root):
        return ""
    if f"?? {path.relative_to(root).as_posix()}" not in changes.splitlines():
        return ""
    return "The spec is one of them: commit it, or pass a --spec path outside the repository."


def _describe(problem: ErrorDetails) -> str:
    field = ".".join(str(part) for part in problem["loc"])
    message = problem["msg"].removeprefix("Value error, ")
    return f"{field}: {message}" if field else message


if __name__ == "__main__":
    main()
