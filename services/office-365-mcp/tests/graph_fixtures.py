import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import httpx
import respx

E2E = Path(__file__).parent / "e2e"
V1 = "/v1.0"

Json = dict[str, object]


def response(spec: Mapping[str, object], bodies: Path = E2E / "bodies") -> httpx.Response:
    named = bodies / str(spec.get("body", ""))
    content = named.read_bytes() if named.is_file() else b""
    headers = {"content-type": "application/json"} if named.suffix == ".json" else {}
    headers.update(cast("Mapping[str, str]", spec.get("response_headers", spec.get("headers", {}))))
    return httpx.Response(cast("int", spec["status"]), content=content, headers=headers)


def serve(router: respx.MockRouter, name: str) -> dict[tuple[str, str], respx.Route]:
    """One route per method and path of the fixture, answering in the recorded order."""
    answers: dict[tuple[str, str], list[httpx.Response]] = defaultdict(list)
    for spec in cast("list[Json]", json.loads((E2E / "fixtures" / f"{name}.json").read_text())):
        method, path = str(spec["method"]), str(spec["path"])
        assert path.startswith(V1), f"{name}: {path} is not a Graph v1.0 path"
        answers[(method, path.removeprefix(V1))].append(response(spec))
    return {
        key: router.route(method=key[0], path=key[1]).mock(side_effect=responses)
        for key, responses in answers.items()
    }
