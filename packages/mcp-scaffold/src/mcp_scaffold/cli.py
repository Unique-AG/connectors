"""Generate a Python MCP, once. From the repository root:

uv run --project packages/mcp-scaffold mcp-scaffold new <name> \\
    --description "<what it does>" --upstream openapi|http|custom [--spec <path or URL>] \\
    --persistence none|postgres|redis [postgres|redis] --auth none|unique

The `new-mcp` skill asks for the options and runs it. The MCP owns every file it generates.
"""

import argparse
import subprocess
from pathlib import Path
from typing import cast

from mcp_scaffold.options import Auth, Options, Persistence, Upstream
from mcp_scaffold.scaffold import scaffold


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-scaffold", description=(__doc__ or "").split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="generate services/<name> and register it")
    new.add_argument("name", help="kebab-case, e.g. weather-mcp")
    new.add_argument("--description", required=True)
    new.add_argument("--upstream", type=Upstream, choices=list(Upstream), required=True)
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
    new.add_argument("--auth", type=Auth, choices=list(Auth), required=True)
    new.add_argument(
        "--no-release",
        dest="release",
        action="store_false",
        help="skip release-please and the release re-run list, as for the demo",
    )
    arguments = parser.parse_args()

    repo = Path.cwd()
    assert (repo / ".gitcommitizen").is_file(), "run mcp-scaffold from the repository root"
    stores = cast(list[str], arguments.persistence)
    if "none" in stores and len(stores) > 1:
        parser.error("--persistence none cannot be combined with a store")
    options = Options.model_validate(
        {**vars(arguments), "persistence": [store for store in stores if store != "none"]}
    )
    _require_clean(parser, repo)
    target = scaffold(options, repo, release=cast(bool, arguments.release))
    print(f"{target} is ready. The new-mcp skill lists what to fill in next.")


def _require_clean(parser: argparse.ArgumentParser, repo: Path) -> None:
    changes = subprocess.run(
        ["git", "status", "--porcelain"],
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


if __name__ == "__main__":
    main()
