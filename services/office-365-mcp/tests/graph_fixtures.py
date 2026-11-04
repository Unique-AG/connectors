import base64
import hashlib
import html
import importlib.util
import json
import re
from collections import defaultdict
from collections.abc import Callable, Mapping
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import cast

import httpx
import respx

E2E = Path(__file__).parent / "e2e"
DOCGEN = Path(__file__).parents[1] / "scripts" / "dogfood" / "seed" / "docgen.py"
V1 = "/v1.0"

Json = dict[str, object]
_LEAF = re.compile(rb'"<generated:([0-9a-f]{64})>"')
_FILLER = re.compile(rb"&lt;generated:filler-text:(\d+):(.+?)&gt;")


@cache
def _docgen() -> ModuleType:
    found = importlib.util.spec_from_file_location("seed_docgen", DOCGEN)
    if found is None or found.loader is None:
        raise ImportError(f"cannot load {DOCGEN}")
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def generate(generator: object, size: object, label: object) -> bytes:
    make = cast("Callable[[object, object, object], bytes]", vars(_docgen())["generate"])
    return make(generator, size, label)


def generated(stub: Path) -> bytes:
    spec = cast("Mapping[str, object]", json.loads(stub.read_text()))
    raw = generate(spec["generator"], spec["size"], spec["label"])
    if len(raw) != spec["size"] or hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise ValueError(f"{stub.name}: the bytes that the generator makes changed")
    return raw


def recorded_json(stem: str) -> Json:
    """The JSON body of interaction N of a recorded fixture, named `<fixture>.<N>`."""
    fixture, _, number = stem.rpartition(".")
    spec = cast("list[Json]", json.loads((E2E / "fixtures" / f"{fixture}.json").read_text()))
    return cast("Json", spec[int(number) - 1]["response_json"])


def response(spec: Mapping[str, object], bodies: Path = E2E / "bodies") -> httpx.Response:
    named = bodies / str(spec.get("body", ""))
    content = named.read_bytes() if named.is_file() else b""
    if "response_json" in spec:
        named = Path("inline.json")
        content = json.dumps(spec["response_json"], ensure_ascii=False).encode()
    if named.suffix == ".gen":
        content = generated(named)
    elif named.suffix == ".json":
        content = _LEAF.sub(
            lambda found: (
                b'"' + base64.b64encode(generated(bodies / f"{found[1].decode()}.gen")) + b'"'
            ),
            content,
        )
    elif named.suffix == ".html":
        content = _FILLER.sub(
            lambda found: generate("filler-text", int(found[1]), html.unescape(found[2].decode())),
            content,
        )
    headers = {"content-type": "application/json"} if named.suffix == ".json" else {}
    headers.update(cast("Mapping[str, str]", spec.get("response_headers", spec.get("headers", {}))))
    return httpx.Response(cast("int", spec["status"]), content=content, headers=headers)


def serve(router: respx.MockRouter, name: str) -> dict[tuple[str, str], respx.Route]:
    """One route per method and path of the fixture, answering in the recorded order. An entry
    with a `host` key (a download on the SharePoint host) routes by that host and its own path."""
    answers: dict[tuple[str, str], list[httpx.Response]] = defaultdict(list)
    routes: dict[tuple[str, str], Json] = {}
    for spec in cast("list[Json]", json.loads((E2E / "fixtures" / f"{name}.json").read_text())):
        method, path, host = str(spec["method"]), str(spec["path"]), spec.get("host")
        if host is None:
            if not path.startswith(V1):
                raise ValueError(f"{name}: {path} is not a Graph v1.0 path")
            path = path.removeprefix(V1)
        key = (method, path if host is None else f"https://{host}{path}")
        answers[key].append(response(spec))
        routes[key] = {"method": method, "path": path} | ({"host": host} if host else {})
    return {
        key: router.route(**routes[key]).mock(side_effect=responses)  # pyright: ignore[reportArgumentType]
        for key, responses in answers.items()
    }
