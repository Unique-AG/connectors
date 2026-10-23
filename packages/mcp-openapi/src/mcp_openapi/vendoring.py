"""A vendored spec: fetched again from where it came from, and the code generated from it."""

import difflib
import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import httpx2
import yaml

HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def refresh_spec(*, spec: Path, source: str | Path) -> list[str]:
    """Write the spec at `source`, a URL or a file, over `spec`, and list the operationIds added
    (`+`) and removed (`-`).

    A JSON spec is written as YAML, as `mcp-scaffold` vendors it with `as_yaml`, so a refresh
    only shows what the vendor changed.
    """
    if isinstance(source, Path):
        text = as_yaml(source.read_text())
    else:
        response = httpx2.get(source, follow_redirects=True)
        response.raise_for_status()
        text = as_yaml(response.text)
    before: set[str] = _operation_ids(spec.read_text()) if spec.is_file() else set()
    after = _operation_ids(text)
    spec.write_text(text)
    return [f"+ {operation}" for operation in sorted(after - before)] + [
        f"- {operation}" for operation in sorted(before - after)
    ]


def as_yaml(spec: str) -> str:
    """`spec` as the YAML a vendored spec is kept in. A YAML spec is kept as the vendor wrote it."""
    if spec.lstrip().startswith("{"):
        return yaml.safe_dump(json.loads(spec), sort_keys=False, allow_unicode=True)
    return spec


def stale_outputs(outputs: list[Path], generate: Callable[[], None]) -> list[str]:
    """Run `generate`, then put every output back as it was. Each one it changed, with a diff."""
    with _restored(outputs) as recorded:
        generate()
        current = {path: path.read_text() if path.is_file() else None for path in outputs}
    return [
        f"{path} is stale:\n"
        + "\n".join(
            difflib.unified_diff(
                (recorded[path] or "").splitlines(),
                (current[path] or "").splitlines(),
                "committed",
                "generated",
                lineterm="",
                n=1,
            )
        )
        for path in outputs
        if recorded[path] != current[path]
    ]


@contextmanager
def _restored(paths: list[Path]) -> Generator[dict[Path, str | None]]:
    recorded = {path: path.read_text() if path.is_file() else None for path in paths}
    try:
        yield recorded
    finally:
        for path, text in recorded.items():
            if text is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(text)


def _operation_ids(text: str) -> set[str]:
    spec = cast(dict[str, object], yaml.safe_load(text) or {})
    paths = cast(dict[str, dict[str, object]], spec.get("paths") or {})
    return {
        str(operation_id)
        for item in paths.values()
        for method, operation in item.items()
        if method in HTTP_METHODS and isinstance(operation, dict)
        for operation_id in [cast(dict[str, object], operation).get("operationId")]
        if operation_id is not None
    }
