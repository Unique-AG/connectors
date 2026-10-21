"""The skeleton every MCP starts as, written for the placeholder package `mcp_skeleton`."""

import json
import shutil
import textwrap
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from mcp_scaffold.options import Options

FILES = Path(__file__).parent / "files"
LAYERS = FILES / "layers"
PACKAGE = "mcp_skeleton"
NAME = "mcp-skeleton"


def copy_skeleton(target: Path) -> None:
    shutil.copytree(FILES / "skeleton", target, symlinks=True)


def render_templates(options: Options, target: Path) -> None:
    """Render each `*.jinja` file the skeleton copied for `options`, in place of the template.
    Layout is left to the ruff format that `commands.check` runs afterwards."""
    environment = Environment(
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    for template in sorted(target.rglob("*.jinja")):
        rendered = environment.from_string(template.read_text()).render(
            options=options, python_lines=_python_lines, quoted=json.dumps
        )
        template.with_suffix("").write_text(rendered)
        template.unlink()


def _python_lines(text: str, width: int) -> list[str]:
    """`text` as adjacent string literals, which Python joins back into it."""
    lines = textwrap.wrap(text, width)
    spaced = [f"{line} " for line in lines[:-1]] + lines[-1:]
    return [json.dumps(line) for line in spaced]


def copy_root_files(kind: str, target: Path) -> None:
    """Files outside the package a choice brings, such as alembic.ini or its own tests."""
    root = FILES / "root" / kind
    if root.is_dir():
        shutil.copytree(root, target, dirs_exist_ok=True)


def rename(options: Options, target: Path) -> None:
    """Replace the placeholders with the new MCP's names, in every file and folder name."""
    (target / "src" / PACKAGE).rename(target / "src" / options.package)
    for path in target.rglob("*"):
        if path.is_file() and not path.is_symlink():
            text = path.read_text()
            renamed = (
                text.replace(PACKAGE, options.package)
                .replace(NAME, options.name)
                .replace(_TITLE, options.title)
            )
            path.write_text(renamed)
    (target / "deploy" / "helm-charts" / NAME).rename(
        target / "deploy" / "helm-charts" / options.name
    )


_TITLE = "MCP Skeleton"
