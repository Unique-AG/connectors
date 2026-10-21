"""The line at the top of every file the scaffold writes: the scaffold's version and the moment
the run started, the same in every file of one run."""

import json
from datetime import datetime
from pathlib import Path


def written_files(target: Path) -> list[Path]:
    """Every file under `target` so far. The scaffold lists them before it runs any tool there,
    so no tool's output, such as `uv.lock` or the codegen's, is among them."""
    return sorted(path for path in target.rglob("*") if path.is_file() and not path.is_symlink())


def stamp(files: list[Path], *, version: str, timestamp: datetime) -> None:
    line = f"mcp-scaffold-version: {version}, timestamp: {timestamp.isoformat(timespec='seconds')}"
    for path in files:
        if path.name not in _REGENERATED:
            path.write_text(stamped(path, line))


def stamped(path: Path, line: str) -> str:
    """`path`'s text with `line` as a comment on top, after a line that has to stay first."""
    text = path.read_text()
    if path.suffix == ".json":
        # JSON has no comments, and every JSON file the scaffold writes is a JSON schema.
        assert text.startswith("{\n"), f"{path.name} is not a JSON object, one key per line"
        return f'{{\n  "$comment": {json.dumps(line)},\n{text[2:]}'
    comment = _comment_syntax(path).format(line)
    if path.suffix == ".py" and text:
        # A comment right above an import is the import's, and moves with it when ruff sorts.
        comment += "\n"
    first, _, rest = text.partition("\n")
    if first.startswith(_FIRST_LINE_ONLY):
        return f"{first}\n{comment}\n{rest}"
    return f"{comment}\n{text}"


def _comment_syntax(path: Path) -> str:
    if path.suffix == ".tpl" or path.parent.name == "templates":
        return _HELM_TEMPLATE
    syntax = _BY_NAME.get(path.name) or _BY_SUFFIX.get(path.suffix)
    assert syntax is not None, f"the scaffold knows no comment syntax for {path.name}"
    return syntax


_HELM_TEMPLATE = "{{{{/* {} */}}}}"
_BY_NAME = dict.fromkeys(
    ["Dockerfile", ".env.example", ".python-version", ".helmignore", "Chart.lock"], "# {}"
)
_BY_SUFFIX = {
    **dict.fromkeys([".py", ".toml", ".yaml", ".yml", ".ini", ".sh"], "# {}"),
    ".md": "<!-- {} -->",
    ".mako": "## {}",
}
# A shebang, and a Dockerfile's parser directive, which BuildKit only reads before any comment.
_FIRST_LINE_ONLY = ("#!", "# syntax=")
# scripts/render-values-schema.sh writes it from the base chart's, and CI fails on any other line.
_REGENERATED = {"values.schema.json"}
