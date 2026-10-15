import asyncio
import json
import re
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest
import yaml
from pydantic import BaseModel, TypeAdapter

from tiingo_mcp.helpers.codegen import generate_response_models
from tiingo_mcp.helpers.headers import only_headers
from tiingo_mcp.helpers.upstream import Operation, OperationClient, UpstreamError


class Row(BaseModel):
    value: int


ROWS = TypeAdapter(list[Row])

SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /things:
    get:
      operationId: getThings
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: array, items: {$ref: "#/components/schemas/Thing"}}
  /things/{name}:
    post:
      operationId: postThing
      parameters:
        - {name: name, in: path, required: true, schema: {type: string}}
        - {name: dry, in: query, schema: {type: boolean}}
        - {name: X-Trace, in: header, schema: {type: string}}
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [label]
              properties: {label: {type: string}, qty: {type: integer}}
      responses:
        "200": {description: ok, content: {application/json: {schema: {type: object}}}}
    get:
      operationId: getThing
      parameters:
        - {name: name, in: path, required: true, schema: {type: string}}
        - {name: since, in: query, schema: {type: string}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Thing"}
components:
  schemas:
    Thing:
      type: object
      properties:
        name: {type: string, maxLength: 5, description: The name.}
        secret: {type: string}
        qty: {type: integer, minimum: 0, maximum: 10}
"""


def api(handler: Callable[[httpx2.Request], httpx2.Response]) -> OperationClient:
    http = httpx2.AsyncClient(
        base_url="https://upstream.example",
        headers={"Authorization": "Token k"},
        transport=httpx2.MockTransport(handler),
    )
    return OperationClient(yaml.safe_load(SPEC), http)


def get_things(body: object, status: int = 200) -> list[Row]:
    client = api(lambda _: httpx2.Response(status, json=body))
    return asyncio.run(client.call(Operation("getThings", ROWS)))


def test_operation_ids_lists_the_operations_of_the_spec() -> None:
    assert api(lambda _: httpx2.Response(200)).operation_ids == {
        "getThings",
        "getThing",
        "postThing",
    }


def test_call_parses_the_body_as_the_adapter_type() -> None:
    assert get_things([{"value": 1}, {"value": 2}]) == [Row(value=1), Row(value=2)]


def test_call_names_the_field_that_does_not_fit() -> None:
    with pytest.raises(UpstreamError, match=r"Unexpected response: 1\.value: "):
        get_things([{"value": 1}, {"value": "x"}])


def test_call_reports_an_error_status() -> None:
    with pytest.raises(UpstreamError, match="404"):
        get_things({"detail": "nope"}, status=404)


def test_call_builds_the_request_from_the_spec() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"value": 1})

    asyncio.run(
        api(handler).call(Operation("getThing", TypeAdapter(Row)), name="a/b", since="2026-01-02")
    )
    request = seen[0]
    assert (request.method, request.url.raw_path) == (
        "GET",
        b"/things/a%2Fb?since=2026-01-02",
    )
    assert request.headers["authorization"] == "Token k"


def test_only_listed_headers_leave_and_fixed_ones_are_set() -> None:
    request = httpx2.Request(
        "GET",
        "https://upstream.example/",
        headers={
            "Authorization": "Bearer caller",
            "X-Forwarded-For": "203.0.113.9",
            "Accept": "*/*",
        },
    )
    asyncio.run(
        only_headers(
            frozenset({"accept"}), {"Authorization": "Token k"}, origin="https://upstream.example"
        )(request)
    )
    assert request.headers["authorization"] == "Token k"
    assert request.headers["accept"] == "*/*"
    assert "x-forwarded-for" not in request.headers


def test_call_error_does_not_include_the_query_string() -> None:
    client = api(lambda _: httpx2.Response(404))
    with pytest.raises(UpstreamError) as error:
        asyncio.run(client.call(Operation("getThing", TypeAdapter(Row)), name="a", since="SECRET"))
    assert str(error.value) == "404 Not Found for GET https://upstream.example/things/a"


def test_call_error_includes_the_start_of_the_response_body() -> None:
    client = api(lambda _: httpx2.Response(404, text='{"detail":"Not found."}'))
    with pytest.raises(UpstreamError, match=r'404 Not Found for GET .*: \{"detail":"Not found."\}'):
        asyncio.run(client.call(Operation("getThings", ROWS)))


def test_call_names_the_body_when_it_is_not_json() -> None:
    client = api(lambda _: httpx2.Response(200, content=b"<html>"))
    with pytest.raises(UpstreamError, match="Unexpected response: body: Invalid JSON"):
        asyncio.run(client.call(Operation("getThings", ROWS)))


def test_call_rejects_an_operation_that_is_not_in_the_spec() -> None:
    client = api(lambda _: httpx2.Response(200, json=[]))
    with pytest.raises(AssertionError, match="operationId getMissing is not in the spec"):
        asyncio.run(client.call(Operation("getMissing", ROWS)))


def test_call_sends_path_query_header_and_body_arguments_where_the_spec_puts_them() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={})

    arguments = {"name": "a/b", "dry": True, "X-Trace": "t1", "label": "x", "qty": 3}
    asyncio.run(api(handler).call(Operation("postThing", TypeAdapter(dict)), **arguments))
    request = seen[0]
    assert (request.method, request.url.raw_path) == ("POST", b"/things/a%2Fb?dry=true")
    assert request.headers["x-trace"] == "t1"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {"label": "x", "qty": 3}
    assert request.headers["authorization"] == "Token k"


def test_call_rejects_an_argument_the_spec_does_not_know() -> None:
    client = api(lambda _: httpx2.Response(200, json={"value": 1}))
    operation = Operation("getThing", TypeAdapter(Row))
    with pytest.raises(
        ValueError, match=r"getThing has no \['sinc'\], it takes \['name', 'since'\]"
    ):
        asyncio.run(client.call(operation, name="a", sinc="2026-01-02"))


@pytest.mark.parametrize(
    ("arguments", "missing"),
    [
        ({"label": "x"}, "['name']"),
        ({"name": "a"}, "['label']"),
        ({"name": "a", "label": None}, "['label']"),
        ({"name": "", "label": "x"}, "['name']"),
    ],
)
def test_call_rejects_a_required_argument_that_is_missing(
    arguments: dict[str, object], missing: str
) -> None:
    client = api(lambda _: httpx2.Response(200, json={}))
    with pytest.raises(ValueError, match=rf"postThing needs {re.escape(missing)}"):
        asyncio.run(client.call(Operation("postThing", TypeAdapter(dict)), **arguments))


def redirected_authorization(location: str, origin: str = "https://upstream.example") -> list:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((str(request.url), request.headers.get("authorization")))
        if len(seen) == 1:
            return httpx2.Response(301, headers={"location": location})
        return httpx2.Response(200, json=[])

    hook = only_headers(frozenset({"host"}), {"Authorization": "Token k"}, origin=origin)

    async def run() -> None:
        async with httpx2.AsyncClient(
            follow_redirects=True,
            transport=httpx2.MockTransport(handler),
            event_hooks={"request": [hook]},
        ) as client:
            await client.get("https://upstream.example/start")

    asyncio.run(run())
    return seen


@pytest.mark.parametrize(
    "location",
    ["https://other.example/x", "http://upstream.example/x", "https://upstream.example:8443/x"],
)
def test_authorization_is_not_sent_to_another_origin_on_a_redirect(location: str) -> None:
    assert redirected_authorization(location) == [
        ("https://upstream.example/start", "Token k"),
        (location, None),
    ]


def test_authorization_follows_a_redirect_within_the_origin() -> None:
    seen = redirected_authorization("https://upstream.example/x")
    assert [auth for _, auth in seen] == ["Token k", "Token k"]


def test_origin_is_matched_case_insensitively() -> None:
    seen = redirected_authorization("https://upstream.example/x", origin="https://Upstream.Example")
    assert seen[0] == ("https://upstream.example/start", "Token k")


def test_the_headers_a_request_cannot_be_sent_without_are_always_kept() -> None:
    request = httpx2.Request("POST", "https://upstream.example/", content=b"{}")
    request.headers["X-Other"] = "1"
    asyncio.run(only_headers(frozenset(), {}, origin="https://upstream.example")(request))
    assert {"host", "content-length"} <= set(request.headers)
    assert "x-other" not in request.headers


def test_allow_list_names_are_case_insensitive() -> None:
    request = httpx2.Request("GET", "https://upstream.example/", headers={"Accept": "*/*"})
    asyncio.run(only_headers(frozenset({"Accept"}), {}, origin="https://upstream.example")(request))
    assert request.headers["accept"] == "*/*"


def generate(
    tmp_path: Path, fields: dict[str, tuple[str, ...]] | None = None, **source: object
) -> str:
    output = tmp_path / "models.py"
    generate_response_models(
        operation_ids=["getThings"],
        fields={"Thing": ("name",)} if fields is None else fields,
        output=output,
        **source,
    )
    return output.read_text()


def test_generated_model_is_trimmed_to_the_listed_fields(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    models = generate(tmp_path, spec_path=spec)
    assert "class Thing(BaseModel)" in models
    assert 'name: str | None = Field(None, description="The name.")' in models
    assert "secret" not in models


def test_spec_is_fetched_from_a_url_with_the_given_client(tmp_path: Path) -> None:
    client = httpx2.Client(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=SPEC))
    )
    models = generate(tmp_path, spec_url="https://spec.example/openapi.yml", client=client)
    assert "class Thing(BaseModel)" in models


def test_exactly_one_spec_source_is_required(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="exactly one"):
        generate(tmp_path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('swagger: "2.0"\n', "got no openapi field"),
        ("<html>not a spec</html>", "got no openapi field"),
        ("key: value: other\n", "not valid YAML or JSON"),
        ("openapi: 3.1.0\n", "got 3.1.0"),
        ("openapi: 3.0.3\ninfo: {title: t, version: '1'}\npaths: {}\n", "no components.schemas"),
    ],
)
def test_a_spec_the_generator_cannot_use_is_rejected(
    tmp_path: Path, content: str, message: str
) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(content)
    with pytest.raises(ValueError, match=message):
        generate(tmp_path, spec_path=spec)


def test_an_operation_missing_from_the_spec_is_named(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    with pytest.raises(AssertionError, match=r"not in the spec: \['getMissing'\]"):
        generate_response_models(
            spec_path=spec,
            operation_ids=["getMissing"],
            fields={},
            output=tmp_path / "models.py",
        )


def test_input_bounds_are_not_carried_into_the_models(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    models = generate(tmp_path, spec_path=spec, fields={})
    assert "qty: int | None" in models
    assert "ge=" not in models and "le=" not in models


def test_a_fields_key_that_names_no_generated_model_is_rejected(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    with pytest.raises(AssertionError, match=r"not generated: \['Thnig'\]"):
        generate(tmp_path, spec_path=spec, fields={"Thnig": ("name",)})


def test_operations_without_a_named_response_schema_are_rejected(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(
        SPEC.replace(
            'schema: {type: array, items: {$ref: "#/components/schemas/Thing"}}',
            "schema: {type: array}",
        )
    )
    with pytest.raises(ValueError, match="has a named response schema"):
        generate(tmp_path, spec_path=spec)
