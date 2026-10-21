"""Generate a Python MCP, once. From the repository root:

uv run --project packages/mcp-scaffold mcp-scaffold new <name> \\
    --description "<what it does>" [--upstream openapi|custom] [--spec <path or URL>] \\
    --persistence none|postgres|redis [postgres|redis]

The `new-mcp` skill asks for the options and runs it. The MCP owns every file it generates.
"""

import argparse
import subprocess
from pathlib import Path
from typing import cast

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from mcp_scaffold.options import Options, Persistence, Upstream
from mcp_scaffold.repository import name_conflict
from mcp_scaffold.scaffold import scaffold


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-scaffold", description=(__doc__ or "").split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="generate services/<name> and register it")
    new.add_argument("name", help="kebab-case, e.g. weather-mcp")
    new.add_argument("--description", required=True)
    new.add_argument(
        "--upstream",
        type=Upstream,
        choices=list(Upstream),
        help="what the MCP calls; leave it out for an MCP without an upstream client",
    )
    new.add_argument(
        "--spec",
        help="the vendor's OpenAPI 3.0 spec, a path or an http(s) URL; --upstream openapi needs it",
    )
    new.add_argument(
        "--persistence",
        nargs="+",
        choices=["none", *Persistence],
        required=True,
        help="none, or every store the MCP owns, e.g. --persistence postgres redis",
    )
    new.add_argument(
        "--no-release",
        dest="release",
        action="store_false",
        help="skip release-please and the release re-run list, as for the demo",
    )
    arguments = parser.parse_args()

    repo = Path.cwd()
    if not (repo / ".gitcommitizen").is_file():
        parser.error("run mcp-scaffold from the repository root")
    stores = cast(list[str], arguments.persistence)
    if "none" in stores and len(stores) > 1:
        parser.error("--persistence none cannot be combined with a store")
    try:
        options = Options.model_validate(
            {**vars(arguments), "persistence": [store for store in stores if store != "none"]}
        )
    except ValidationError as error:
        parser.error("\n".join(_describe(problem) for problem in error.errors()))
    if (conflict := name_conflict(options.name, repo)) is not None:
        parser.error(conflict)
    _require_clean(parser, repo)
    target = scaffold(options, repo, release=cast(bool, arguments.release))
    print(f"{target} is ready. The new-mcp skill lists what to fill in next.")


def _require_clean(parser: argparse.ArgumentParser, repo: Path) -> None:
    changes = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if changes:
        parser.error(
            "commit or stash every change first, untracked files too, so git alone can undo "
            f"the run:\n{changes}"
        )


def _describe(problem: ErrorDetails) -> str:
    field = ".".join(str(part) for part in problem["loc"])
    message = problem["msg"].removeprefix("Value error, ")
    return f"{field}: {message}" if field else message


if __name__ == "__main__":
    main()
