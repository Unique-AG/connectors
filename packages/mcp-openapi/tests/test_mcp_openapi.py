import asyncio
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import cast

import httpx2
import pytest
import yaml
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType
from fastmcp.tools import Tool
from pydantic import BaseModel, TypeAdapter, ValidationError

from mcp_openapi.cli import main
from mcp_openapi.codegen import generate_operations, generate_response_models
from mcp_openapi.headers import only_headers
from mcp_openapi.openapi import mcp_name, route_map, set_tool_hints
from mcp_openapi.upstream import Operation, OperationClient, UpstreamError


class Row(BaseModel):
    value: int


ROWS = TypeAdapter(list[Row])
OBJECT = TypeAdapter(dict[str, object])

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
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                properties: {ok: {type: boolean}, other: {type: string}}
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


def load_spec(text: str) -> dict[str, object]:
    return cast(dict[str, object], yaml.safe_load(text))


POST_THING_FIELDS = "                properties: {ok: {type: boolean}, other: {type: string}}\n"


def api(handler: Callable[[httpx2.Request], httpx2.Response]) -> OperationClient:
    http = httpx2.AsyncClient(
        base_url="https://upstream.example",
        headers={"Authorization": "Token k"},
        transport=httpx2.MockTransport(handler),
    )
    return OperationClient(load_spec(SPEC), http)


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
    asyncio.run(api(handler).call(Operation("postThing", OBJECT), **arguments))
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
        asyncio.run(client.call(Operation("postThing", OBJECT), **arguments))


def redirected_authorization(
    location: str, origin: str = "https://upstream.example"
) -> list[tuple[str, str | None]]:
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
    tmp_path: Path,
    fields: dict[str, tuple[str, ...]] | None = None,
    spec_path: Path | None = None,
    spec_url: str | None = None,
    client: httpx2.Client | None = None,
) -> str:
    output = tmp_path / "models.py"
    generate_response_models(
        operation_ids=["getThings"],
        fields={"Thing": ("name",)} if fields is None else fields,
        output=output,
        spec_path=spec_path,
        spec_url=spec_url,
        client=client,
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
    with pytest.raises(ValueError, match="has a response schema to generate"):
        generate(tmp_path, spec_path=spec)


def operations_for(tmp_path: Path, operation_ids: list[str], spec_text: str = SPEC) -> str:
    spec = tmp_path / "spec.yml"
    spec.write_text(spec_text)
    output = tmp_path / "operations.py"
    generate_operations(
        spec_path=spec,
        operation_ids=operation_ids,
        operation_module="mcp_openapi.upstream",
        models_module="models",
        output=output,
    )
    return output.read_text()


def test_each_operation_gets_a_constant_typed_with_its_response(tmp_path: Path) -> None:
    generated = operations_for(tmp_path, ["getThings", "getThing"])
    assert 'GET_THINGS = Operation("getThings", TypeAdapter(list[Thing]))' in generated
    assert 'GET_THING = Operation("getThing", TypeAdapter(Thing))' in generated
    assert "from models import Thing\n" in generated


def test_generated_operations_keep_first_party_and_third_party_imports_apart(
    tmp_path: Path,
) -> None:
    (tmp_path / "models.py").write_text("")
    (tmp_path / "ruff.toml").write_text('src = ["."]\n')
    operations_for(tmp_path, ["getThings"])
    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "I", str(tmp_path / "operations.py")],
        check=True,
        cwd=tmp_path,
    )


def test_a_constant_for_an_operation_without_an_object_or_named_response_is_refused(
    tmp_path: Path,
) -> None:
    spec_text = SPEC.replace(" " * 16 + "type: object\n", " " * 16 + "type: string\n")
    assert POST_THING_FIELDS in spec_text
    with pytest.raises(ValueError, match="postThing: the success response is not an object"):
        operations_for(tmp_path, ["postThing"], spec_text)


def test_a_response_written_in_place_gets_a_model_named_after_its_operation(
    tmp_path: Path,
) -> None:
    generated = operations_for(tmp_path, ["postThing"])
    assert 'POST_THING = Operation("postThing", TypeAdapter(PostThingResponse))' in generated
    assert "from models import PostThingResponse\n" in generated


def models_for(
    tmp_path: Path,
    spec_text: str,
    operation_ids: list[str],
    fields: dict[str, tuple[str, ...]] | None = None,
    allow_extra_fields: bool = False,
) -> str:
    spec = tmp_path / "spec.yml"
    spec.write_text(spec_text)
    output = tmp_path / "models.py"
    generate_response_models(
        spec_path=spec,
        operation_ids=operation_ids,
        fields=fields,
        allow_extra_fields=allow_extra_fields,
        output=output,
    )
    return output.read_text()


def _model(tmp_path: Path, name: str) -> type[BaseModel]:
    module = ModuleType("generated_models")
    sys.modules[module.__name__] = module
    source = (tmp_path / "models.py").read_text()
    exec(compile(source, str(tmp_path / "models.py"), "exec"), module.__dict__)  # noqa: S102
    return cast(type[BaseModel], getattr(module, name))


def validated(tmp_path: Path, name: str, payload: Mapping[str, object]) -> dict[str, object]:
    return _model(tmp_path, name).model_validate(payload).model_dump()


def test_models_drop_undeclared_fields_unless_asked_to_keep_them(tmp_path: Path) -> None:
    body = {"name": "a", "unknown": "x"}
    models_for(tmp_path, SPEC, ["getThing"])
    assert "unknown" not in validated(tmp_path, "Thing", body)
    models_for(tmp_path, SPEC, ["getThing"], allow_extra_fields=True)
    assert validated(tmp_path, "Thing", body)["unknown"] == "x"


def test_a_field_cut_by_fields_stays_as_an_extra_when_extra_fields_are_kept(
    tmp_path: Path,
) -> None:
    models_for(tmp_path, SPEC, ["getThing"], fields={"Thing": ("name",)}, allow_extra_fields=True)
    assert "secret" not in _model(tmp_path, "Thing").model_fields
    assert validated(tmp_path, "Thing", {"name": "a", "secret": "s"})["secret"] == "s"


STRICT_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /strict:
    get:
      operationId: getStrict
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Strict"}
components:
  schemas:
    Strict:
      type: object
      additionalProperties: false
      properties: {a: {type: string}, secret: {type: string}}
"""


def test_a_model_trimmed_to_fields_accepts_the_fields_it_cut(tmp_path: Path) -> None:
    models_for(tmp_path, STRICT_SPEC, ["getStrict"], fields={"Strict": ("a",)})
    assert validated(tmp_path, "Strict", {"a": "1", "secret": "s"}) == {"a": "1"}


def test_a_model_written_for_a_response_in_place_has_the_fields_of_that_response(
    tmp_path: Path,
) -> None:
    generated = models_for(tmp_path, SPEC, ["postThing"])
    assert "class PostThingResponse(BaseModel):" in generated
    assert "ok: bool | None" in generated


def test_fields_trim_a_model_written_for_a_response_in_place(tmp_path: Path) -> None:
    generated = models_for(tmp_path, SPEC, ["postThing"], fields={"PostThingResponse": ("ok",)})
    assert "ok: bool | None" in generated
    assert "other" not in generated


def test_an_object_without_fields_is_not_made_into_an_empty_model(tmp_path: Path) -> None:
    spec_text = SPEC.replace(POST_THING_FIELDS, "")
    with pytest.raises(ValueError, match="postThing: the success response is not an object"):
        operations_for(tmp_path, ["postThing"], spec_text)


ONE_OF_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /either:
    get:
      operationId: get-either
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                oneOf:
                  - $ref: "#/components/schemas/A"
                  - $ref: "#/components/schemas/B"
components:
  schemas:
    A: {type: object, properties: {a: {type: string}}}
    B: {type: object, properties: {b: {type: string}}}
"""


def test_a_oneof_response_written_in_place_is_generated_with_its_alternatives(
    tmp_path: Path,
) -> None:
    generated = models_for(tmp_path, ONE_OF_SPEC, ["get-either"])
    assert "GetEitherResponse" in generated
    assert "A | B" in generated


def test_two_operations_cannot_make_the_same_model_name(tmp_path: Path) -> None:
    spec_text = ENVELOPE_SPEC.replace("components:", SECOND_COMPANIES_PATH + "components:")
    with pytest.raises(AssertionError, match="two operationIds make the model name"):
        models_for(tmp_path, spec_text, ["get-companies", "getCompanies"])


def test_two_operations_cannot_make_the_same_constant_name(tmp_path: Path) -> None:
    spec_text = SPEC.replace("operationId: getThing\n", "operationId: get-things\n")
    with pytest.raises(AssertionError, match="same constant name"):
        operations_for(tmp_path, ["getThings", "get-things"], spec_text)


def test_an_operation_id_that_does_not_make_a_valid_name_is_refused(tmp_path: Path) -> None:
    spec_text = SPEC.replace("operationId: postThing", "operationId: 2fa-status")
    with pytest.raises(AssertionError, match="invalid model name"):
        models_for(tmp_path, spec_text, ["2fa-status"])


SECOND_COMPANIES_PATH = """  /other:
    get:
      operationId: getCompanies
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: object, properties: {x: {type: string}}}
"""

ENVELOPE_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /companies:
    get:
      operationId: get-companies
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                allOf:
                  - $ref: "#/components/schemas/BaseResponse"
                  - type: object
                    properties:
                      data: {type: array, items: {$ref: "#/components/schemas/Company"}}
components:
  schemas:
    BaseResponse:
      type: object
      properties: {details: {type: string}}
    Company:
      type: object
      properties: {name: {type: string}}
"""


def test_an_allof_envelope_written_in_place_is_generated_with_the_schemas_it_uses(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(ENVELOPE_SPEC)
    models = tmp_path / "models.py"
    generate_response_models(spec_path=spec, operation_ids=["get-companies"], output=models)
    generated = models.read_text()
    assert "class GetCompaniesResponse(BaseResponse):" in generated
    assert "data: list[Company] | None" in generated
    assert 'GET_COMPANIES = Operation("get-companies", TypeAdapter(GetCompaniesResponse))' in (
        operations_for(tmp_path, ["get-companies"], ENVELOPE_SPEC)
    )


def test_a_model_name_made_from_an_operation_cannot_replace_a_schema_of_the_spec(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(
        ENVELOPE_SPEC.replace(
            "    Company:", "    GetCompaniesResponse:\n      type: object\n    Company:"
        )
    )
    with pytest.raises(AssertionError, match=r"already has \['GetCompaniesResponse'\]"):
        generate_response_models(
            spec_path=spec, operation_ids=["get-companies"], output=tmp_path / "models.py"
        )


def test_a_constant_for_an_operation_missing_from_the_spec_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match=r"not in the spec: \['getMissing'\]"):
        operations_for(tmp_path, ["getMissing"])


NESTED_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /parents:
    get:
      operationId: getParents
      responses:
        "200": {$ref: "#/components/responses/Parents"}
  /dangling:
    get:
      operationId: getDangling
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Missing"}
components:
  responses:
    Parents:
      description: ok
      content:
        application/json; charset=utf-8:
          schema: {type: array, items: {$ref: "#/components/schemas/Parent"}}
  schemas:
    Parent:
      type: object
      properties:
        kid: {$ref: "#/components/schemas/Kid"}
      additionalProperties: {$ref: "#/components/schemas/Extra"}
    Kid:
      type: object
      properties:
        leaf: {allOf: [{$ref: "#/components/schemas/Leaf"}]}
    Leaf: {type: object, properties: {name: {type: string}}}
    Extra: {type: object, properties: {note: {type: string}}}
    Unused: {type: object, properties: {name: {type: string}}}
"""


def models_from_nested_spec(tmp_path: Path, operation_id: str) -> Path:
    spec = tmp_path / "spec.yml"
    spec.write_text(NESTED_SPEC)
    output = tmp_path / "models.py"
    generate_response_models(spec_path=spec, operation_ids=[operation_id], fields={}, output=output)
    return output


def test_every_schema_a_response_reaches_is_generated_and_no_other(tmp_path: Path) -> None:
    models = models_from_nested_spec(tmp_path, "getParents").read_text()
    classes = {
        line.split("(")[0].removeprefix("class ")
        for line in models.splitlines()
        if line.startswith("class ")
    }
    assert classes == {"Parent", "Kid", "Leaf", "Extra"}


def test_a_response_that_refers_to_a_missing_schema_is_named(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="Missing is referenced but not in components.schemas"):
        models_from_nested_spec(tmp_path, "getDangling")


def test_a_response_defined_in_components_is_resolved(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(NESTED_SPEC)
    output = tmp_path / "operations.py"
    generate_operations(
        spec_path=spec,
        operation_ids=["getParents"],
        operation_module="mcp_openapi.upstream",
        models_module="models",
        output=output,
    )
    assert 'GET_PARENTS = Operation("getParents", TypeAdapter(list[Parent]))' in output.read_text()


@pytest.mark.parametrize(
    ("operation_id", "remove_prefix", "expected"),
    [
        ("getDailyPrices", "", "get_daily_prices"),
        ("getDailyPrices", "get_", "daily_prices"),
        ("testConnection", "get_", "test_connection"),
        ("get-companies-kyckrId", "", "get_companies_kyckr_id"),
        ("post-orders", "post_", "orders"),
        ("get2FaStatus", "", "get2_fa_status"),
    ],
)
def test_mcp_name_is_snake_case_for_camel_and_kebab_case_ids(
    operation_id: str, remove_prefix: str, expected: str
) -> None:
    assert mcp_name(operation_id, remove_prefix=remove_prefix) == expected


def served_tools(exposed: dict[str, MCPType]) -> dict[str, Tool]:
    mcp = FastMCP.from_openapi(
        openapi_spec=load_spec(SPEC),
        client=httpx2.AsyncClient(base_url="https://upstream.example"),
        route_map_fn=route_map(exposed),
        mcp_component_fn=set_tool_hints,
    )
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def test_route_map_serves_the_listed_operations_and_hides_the_rest() -> None:
    assert set(served_tools({"getThings": MCPType.TOOL, "postThing": MCPType.TOOL})) == {
        "getThings",
        "postThing",
    }


def test_generated_tools_are_open_world_and_read_only_only_for_get() -> None:
    tools = served_tools({"getThings": MCPType.TOOL, "postThing": MCPType.TOOL})
    hints = {
        name: (tool.annotations.read_only_hint, tool.annotations.open_world_hint)
        for name, tool in tools.items()
        if tool.annotations
    }
    assert hints == {"getThings": (True, True), "postThing": (False, True)}


SHAPES_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /typed:
    get:
      operationId: get-typed
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                allOf:
                  - $ref: "#/components/schemas/Base"
                  - properties: {rows: {type: array, items: {$ref: "#/components/schemas/Row"}}}
  /untyped:
    get:
      operationId: get-untyped
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                properties: {total: {type: integer}}
  /empty:
    delete:
      operationId: delete-empty
      responses:
        "204": {description: gone}
components:
  schemas:
    Base:
      type: object
      properties: {kind: {type: string, enum: [a], pattern: "^a$"}}
    Row:
      type: object
      properties: {size: {type: integer, minimum: 1}, tag: {type: string, enum: [x]}}
"""

_OK = """        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Thing"}"""
_ACCEPTED_THEN_OK = (
    """        "202":
          description: accepted
          content:
            application/json:
              schema: {type: array, items: {$ref: "#/components/schemas/Thing"}}
"""
    + _OK
)
TWO_CODES_SPEC = SPEC.replace(_OK, _ACCEPTED_THEN_OK)


def test_an_object_with_allof_or_with_fields_but_no_type_is_a_model_written_in_place(
    tmp_path: Path,
) -> None:
    models_for(tmp_path, SHAPES_SPEC, ["get-typed", "get-untyped"])
    assert validated(tmp_path, "GetUntypedResponse", {"total": 3}) == {"total": 3}
    assert validated(tmp_path, "GetTypedResponse", {"kind": "a"})["kind"] == "a"


def test_input_constraints_are_not_carried_into_the_models_inside_allof_and_arrays(
    tmp_path: Path,
) -> None:
    models_for(tmp_path, SHAPES_SPEC, ["get-typed"])
    reply = validated(
        tmp_path, "GetTypedResponse", {"kind": "other", "rows": [{"size": 0, "tag": "other"}]}
    )
    assert reply["kind"] == "other"
    assert reply["rows"] == [{"size": 0, "tag": "other"}]


def test_a_response_without_a_json_body_is_named(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="delete-empty: the success response has no JSON body"):
        operations_for(tmp_path, ["delete-empty"], SHAPES_SPEC)


def test_an_operation_id_without_letters_or_digits_is_refused(tmp_path: Path) -> None:
    spec_text = SPEC.replace("operationId: getThings", 'operationId: "--"')
    with pytest.raises(AssertionError, match="invalid constant name"):
        operations_for(tmp_path, ["--"], spec_text)
    spec_text = SPEC.replace("operationId: postThing", 'operationId: "--"')
    with pytest.raises(AssertionError, match="no letters or digits"):
        models_for(tmp_path, spec_text, ["--"])


def test_an_operation_id_with_characters_a_name_would_lose_is_refused(tmp_path: Path) -> None:
    spec_text = SPEC.replace("operationId: getThings", "operationId: getÜbersicht")
    with pytest.raises(AssertionError, match="characters"):
        operations_for(tmp_path, ["getÜbersicht"], spec_text)


def test_the_lowest_success_code_gives_the_model_of_an_operation(tmp_path: Path) -> None:
    generated = operations_for(tmp_path, ["getThing"], TWO_CODES_SPEC)
    assert 'GET_THING = Operation("getThing", TypeAdapter(Thing))' in generated


def test_arguments_that_are_none_are_not_sent() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"name": "a"})

    asyncio.run(api(handler).call(Operation("getThing", OBJECT), name="a", since=None))

    assert seen[0].url.query == b""


def test_a_timeout_is_an_upstream_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    with pytest.raises(UpstreamError, match="timed out"):
        asyncio.run(api(handler).call(Operation("getThings", ROWS)))


def test_the_error_body_in_the_message_is_cut_at_200_characters() -> None:
    with pytest.raises(UpstreamError) as raised:
        get_things({"detail": "x" * 500}, status=502)
    assert len(str(raised.value)) < 300


INLINE_ONLY_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /in:
    get:
      operationId: getIn
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: object, properties: {a: {type: string}}}
  /map:
    get:
      operationId: getMap
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: object, additionalProperties: {type: string}}
"""


def test_a_spec_without_components_generates_the_models_written_in_place(tmp_path: Path) -> None:
    models_for(tmp_path, INLINE_ONLY_SPEC, ["getIn"])
    assert validated(tmp_path, "GetInResponse", {"a": "x"}) == {"a": "x"}


def test_a_response_that_is_a_map_is_a_model_written_in_place(tmp_path: Path) -> None:
    models_for(tmp_path, INLINE_ONLY_SPEC, ["getMap"])
    assert validated(tmp_path, "GetMapResponse", {"any": "x"}) == {"any": "x"}


def test_an_operation_id_with_a_quote_still_writes_a_module_that_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_text = SPEC.replace("operationId: getThings", 'operationId: "get\\"x"')
    models_for(tmp_path, spec_text, ["getThing"])
    generated = operations_for(tmp_path, ['get"x'], spec_text)
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    monkeypatch.delitem(sys.modules, "models", raising=False)
    namespace: dict[str, object] = {}
    exec(compile(generated, "operations.py", "exec"), namespace)  # noqa: S102
    operation = cast(Operation[object], namespace["GET_X"])
    assert operation.operation_id == 'get"x'


def test_an_operation_id_with_characters_a_model_name_would_lose_is_refused(
    tmp_path: Path,
) -> None:
    spec_text = SPEC.replace("operationId: postThing", "operationId: postÜbersicht")
    with pytest.raises(AssertionError, match="characters a name would lose"):
        models_for(tmp_path, spec_text, ["postÜbersicht"])


CODEGEN_CONFIG = """
[tool.mcp-openapi]
spec = "spec.yml"
operation-ids = ["getThings"]
operation-module = "mcp_openapi.upstream"
models-module = "models"
models-output = "out/models.py"
operations-output = "out/operations.py"
"""


def test_cli_generates_models_and_operations_from_the_pyproject_table(tmp_path: Path) -> None:
    (tmp_path / "spec.yml").write_text(SPEC)
    (tmp_path / "pyproject.toml").write_text(
        CODEGEN_CONFIG + '[tool.mcp-openapi.fields]\nThing = ["name"]\n'
    )
    (tmp_path / "out").mkdir()

    main([str(tmp_path)])

    assert "class Thing(BaseModel)" in (tmp_path / "out/models.py").read_text()
    assert "GET_THINGS" in (tmp_path / "out/operations.py").read_text()


def test_cli_generates_models_for_more_operations_than_it_makes_constants_for(
    tmp_path: Path,
) -> None:
    (tmp_path / "spec.yml").write_text(SPEC)
    config = CODEGEN_CONFIG.replace(
        'operation-ids = ["getThings"]',
        'operation-ids = ["getThings"]\nresponse-operation-ids = ["getThings", "postThing"]',
    )
    (tmp_path / "pyproject.toml").write_text(config)
    (tmp_path / "out").mkdir()

    main([str(tmp_path)])

    assert "POST_THING" not in (tmp_path / "out/operations.py").read_text()
    assert "PostThingResponse" in (tmp_path / "out/models.py").read_text()


def test_cli_rejects_an_unknown_key_in_the_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(CODEGEN_CONFIG + "operation-id = []\n")

    with pytest.raises(ValidationError, match="operation-id"):
        main([str(tmp_path)])


def test_cli_imports_an_operation_id_list_given_as_module_and_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "codegen_routes_fixture.py").write_text(
        'IDS = ["getThings"]\nFIELDS = {"Thing": ("name",)}\n'
    )
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    (tmp_path / "spec.yml").write_text(SPEC)
    (tmp_path / "pyproject.toml").write_text(
        CODEGEN_CONFIG.replace('["getThings"]', '"codegen_routes_fixture:IDS"')
        + 'fields = "codegen_routes_fixture:FIELDS"\n'
    )
    (tmp_path / "out").mkdir()

    main([str(tmp_path)])

    assert "GET_THINGS" in (tmp_path / "out/operations.py").read_text()
    assert "secret" not in (tmp_path / "out/models.py").read_text()


def test_cli_rejects_an_operation_id_reference_without_a_name(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(CODEGEN_CONFIG.replace('["getThings"]', '"routes"'))

    with pytest.raises(ValidationError, match="module:NAME"):
        main([str(tmp_path)])
