#!/usr/bin/env python3
"""Query the public With Intelligence OpenAPI spec. No credentials needed.

    uv run agent-explore/spec.py paths                  # every path, or those matching a filter
    uv run agent-explore/spec.py paths investor
    uv run agent-explore/spec.py params /v3/investors   # query parameters, with descriptions
    uv run agent-explore/spec.py schema InvestorExtended
    uv run agent-explore/spec.py response '/v3/investors/{id}'

Run it through `uv run` from the service root: it imports httpx from the service's venv, which
the system interpreter does not have.

The spec is ~456 KB across 143 paths and 267 schemas — far too big to read whole, and dumping it
into a conversation wastes the context it was meant to save. So this caches it once and answers
one question at a time, in tab-separated lines.

Behaviour comes from a live GET (`explore.py`), not from here: the spec says an endpoint takes
`primary_strategy_id`, never which ids exist or what a 403 means for your subscription.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx
from pydantic import TypeAdapter

SPEC_URL = "https://api.withintelligence.com/v3/docs/json"
_CACHE = Path(__file__).resolve().parent / ".spec-cache" / "openapi.json"

# `object` rather than a recursive JSON alias: this walks a handful of known keys and narrows at
# each step, which reads better than threading a union through every access.
Json = dict[str, object]

# `json.loads` is typed as returning `Any`, which this service's type-checking mode forbids.
_JSON = TypeAdapter(object)


class _Args(argparse.Namespace):
    command: str
    target: str
    refresh: bool

    def __init__(self) -> None:
        super().__init__()
        self.command = ""
        self.target = ""
        self.refresh = False


def _as_dict(value: object) -> Json:
    return cast("Json", value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _at(mapping: Json, *keys: str) -> Json:
    """Walk a chain of dict keys, yielding `{}` at the first one that isn't there."""
    current = mapping
    for key in keys:
        current = _as_dict(current.get(key))
    return current


def load_spec(refresh: bool) -> Json:
    if _CACHE.exists() and not refresh:
        return _as_dict(_JSON.validate_json(_CACHE.read_text()))
    _CACHE.parent.mkdir(exist_ok=True)
    response = httpx.get(SPEC_URL, timeout=120.0, follow_redirects=True)
    _ = response.raise_for_status()
    _CACHE.write_text(response.text)
    return _as_dict(_JSON.validate_json(response.text))


def _ref_name(ref: str) -> str:
    """The schema name a `#/components/schemas/X` reference points at."""
    return ref.rsplit("/", 1)[-1]


def _schema(spec: Json, name: str) -> Json:
    return _as_dict(_at(spec, "components", "schemas").get(_ref_name(name)))


def _type_of(schema: Json) -> str:
    """A field's type as one readable token — a schema name for a `$ref`, `array<X>` for a list."""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return _ref_name(ref)
    kind = _as_str(schema.get("type"))
    if kind == "array":
        return f"array<{_type_of(_as_dict(schema.get('items')))}>"
    return kind or "object"


def _get_operation(spec: Json, path: str) -> Json:
    operation = _at(spec, "paths", path, "get")
    if not operation:
        raise SystemExit(f"no GET operation for {path!r} — try: paths")
    return operation


def cmd_paths(spec: Json, target: str) -> None:
    paths = _as_dict(spec.get("paths"))
    for path in sorted(paths):
        if target.lower() not in path.lower():
            continue
        methods = ", ".join(sorted(method.upper() for method in _as_dict(paths[path])))
        print(f"{path}\t{methods}")


def cmd_params(spec: Json, target: str) -> None:
    for entry in _as_list(_get_operation(spec, target).get("parameters")):
        parameter = _as_dict(entry)
        description = " ".join(_as_str(parameter.get("description")).split())
        required = "required" if parameter.get("required") else ""
        name = _as_str(parameter.get("name"))
        print(f"{name}\t{_type_of(_as_dict(parameter.get('schema')))}\t{required}\t{description}")


def cmd_schema(spec: Json, target: str) -> None:
    schema = _schema(spec, target)
    if not schema:
        raise SystemExit(f"no schema named {target!r}")
    required = {_as_str(name) for name in _as_list(schema.get("required"))}
    for field, definition in _as_dict(schema.get("properties")).items():
        field_schema = _as_dict(definition)
        description = " ".join(_as_str(field_schema.get("description")).split())
        marker = "required" if field in required else ""
        print(f"{field}\t{_type_of(field_schema)}\t{marker}\t{description}")


def cmd_response(spec: Json, target: str) -> None:
    responses = _as_dict(_get_operation(spec, target).get("responses"))
    for status, entry in responses.items():
        response = _as_dict(entry)
        schema = _at(response, "content", "application/json", "schema")
        shape = _type_of(schema) if schema else ""
        print(f"{status}\t{shape}\t{_as_str(response.get('description'))}")


_COMMANDS: dict[str, Callable[[Json, str], None]] = {
    "paths": cmd_paths,
    "params": cmd_params,
    "schema": cmd_schema,
    "response": cmd_response,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("command", choices=sorted(_COMMANDS))
    _ = parser.add_argument("target", nargs="?", default="")
    _ = parser.add_argument("--refresh", action="store_true", help="re-fetch the cached spec")
    args = parser.parse_args(namespace=_Args())

    if args.command != "paths" and not args.target:
        raise SystemExit(f"{args.command} needs a target")
    _COMMANDS[args.command](load_spec(args.refresh), args.target)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Piping into `head` closes the pipe mid-print, which is the normal way to read this
        # output — a traceback there says nothing and buries the lines you asked for.
        sys.stderr.close()
