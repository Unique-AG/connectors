"""A vendored spec: fetched again from where it came from, and the code generated from it."""

import difflib
import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import httpx2
import yaml

_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def refresh_spec(
    *, spec: Path, source: str | Path, client: httpx2.Client | None = None
) -> list[str]:
    """Write the spec at `source`, a URL or a file, over `spec`, and list the operationIds added
    (`+`) and removed (`-`).

    A JSON spec is written as YAML, the way `mcp-scaffold` vendors it, so a refresh only shows
    what the vendor changed.
    """
    if isinstance(source, Path):
        text = source.read_text()
    else:
        response = client.get(source) if client else httpx2.get(source, follow_redirects=True)
        response.raise_for_status()
        text = response.text
    if text.lstrip().startswith("{"):
        text = yaml.safe_dump(json.loads(text), sort_keys=False, allow_unicode=True)
    before: set[str] = _operation_ids(spec.read_text()) if spec.is_file() else set()
    after = _operation_ids(text)
    spec.write_text(text)
    return [f"+ {operation}" for operation in sorted(after - before)] + [
        f"- {operation}" for operation in sorted(before - after)
    ]


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
        if method in _HTTP_METHODS and isinstance(operation, dict)
        for operation_id in [cast(dict[str, object], operation).get("operationId")]
        if operation_id is not None
    }
