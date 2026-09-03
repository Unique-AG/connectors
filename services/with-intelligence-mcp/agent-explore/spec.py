"""Query the public With Intelligence OpenAPI spec. No credentials needed.

    uv run agent-explore/spec.py paths [filter]
    uv run agent-explore/spec.py params /v3/investors
    uv run agent-explore/spec.py schema InvestorExtended
    uv run agent-explore/spec.py response '/v3/investors/{id}'
    uv run agent-explore/spec.py snapshot            # refresh tests/spec/vendor_schemas.json

Through `uv run`: it imports httpx from the service venv. Output is tab-separated.

Shapes only. Behaviour comes from a live GET (`explore.py`) — the spec says an endpoint takes
`primary_strategy_id`, never which ids exist or what a 403 means for your subscription.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
from pydantic import TypeAdapter

SPEC_URL = "https://api.withintelligence.com/v3/docs/json"
_CACHE = Path(__file__).resolve().parent / ".spec-cache" / "openapi.json"

Json = dict[str, object]

# `json.loads` returns `Any`, which this service's type-checking mode forbids.
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


# The schemas `tests/test_spec_conformance.py` checks our models against, plus everything they
# reference. Add a name here when a feature starts modelling it.
SNAPSHOT_ROOTS = (
    "Investor",
    "InvestorExtended",
    "PaginatedInvestor",
    "Person",
    "PersonExtended",
    "PaginatedPerson",
    "Investment",
    "InvestmentExtended",
    "PaginatedInvestment",
    "Mandate",
    "MandateExtended",
    "PaginatedMandate",
    "Auth",
)
_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "tests" / "spec" / "vendor_schemas.json"


def _referenced_schemas(spec: Json, roots: tuple[str, ...]) -> dict[str, Json]:
    """The named schemas reachable from `roots`, following `$ref` transitively."""
    all_schemas = _at(spec, "components", "schemas")
    collected: dict[str, Json] = {}
    queue = list(roots)
    while queue:
        name = queue.pop()
        if name in collected:
            continue
        schema = _as_dict(all_schemas.get(name))
        if not schema:
            continue
        collected[name] = schema
        queue.extend(_refs_in(schema))
    return collected


def _refs_in(node: object) -> list[str]:
    if isinstance(node, dict):
        entries = cast("Json", node)
        found: list[str] = []
        for key, value in entries.items():
            if key == "$ref" and isinstance(value, str):
                found.append(_ref_name(value))
            else:
                found.extend(_refs_in(value))
        return found
    if isinstance(node, list):
        return [ref for item in cast("list[object]", node) for ref in _refs_in(item)]
    return []


def cmd_snapshot(spec: Json, _target: str) -> None:
    """Write the pruned snapshot the conformance test reads.

    Only the schemas we model are kept, so the committed file stays small enough to read in a
    diff — refreshing it is then a visible change to the vendor contract we depend on.
    """
    schemas = _referenced_schemas(spec, SNAPSHOT_ROOTS)
    payload = {
        "_source": SPEC_URL,
        "_fetched": datetime.now(UTC).date().isoformat(),
        "_roots": list(SNAPSHOT_ROOTS),
        "schemas": dict(sorted(schemas.items())),
    }
    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ = _SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    print(f"wrote {_SNAPSHOT_PATH.relative_to(Path.cwd())} with {len(schemas)} schemas")


_COMMANDS: dict[str, Callable[[Json, str], None]] = {
    "paths": cmd_paths,
    "params": cmd_params,
    "schema": cmd_schema,
    "response": cmd_response,
    "snapshot": cmd_snapshot,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("command", choices=sorted(_COMMANDS))
    _ = parser.add_argument("target", nargs="?", default="")
    _ = parser.add_argument("--refresh", action="store_true", help="re-fetch the cached spec")
    args = parser.parse_args(namespace=_Args())

    if args.command not in ("paths", "snapshot") and not args.target:
        raise SystemExit(f"{args.command} needs a target")
    _COMMANDS[args.command](load_spec(args.refresh), args.target)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Piping into `head` is the normal way to read this; a traceback there says nothing.
        sys.stderr.close()
