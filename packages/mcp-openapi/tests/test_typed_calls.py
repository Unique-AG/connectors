import asyncio
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast

import httpx2
import pytest
import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from mcp_openapi.cli import CodegenConfig
from mcp_openapi.codegen import (
    generate_operations,
    generate_request_models,
    generate_response_models,
)
from mcp_openapi.upstream import Operation, OperationClient

SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /cases/{caseId}:
    parameters:
      - {name: caseId, in: path, required: true, description: The case., schema: {type: string}}
    patch:
      operationId: updateCase
      parameters:
        - {name: screenMode, in: query, schema: {type: string, enum: [SYNC, NONE]}}
        - {name: tags, in: query, schema: {type: array, items: {type: string}}}
        - {name: X-Trace, in: header, schema: {type: string}}
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: "#/components/schemas/CaseUpdate"}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Case"}
  /cases:
    post:
      operationId: createCase
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [caseName]
              properties: {caseName: {type: string, maxLength: 5}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Case"}
  /flags/{enabled}:
    put:
      operationId: setFlag
      parameters:
        - {name: enabled, in: path, required: true, schema: {type: boolean}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Case"}
  /reports/{ids}:
    get:
      operationId: getReports
      parameters:
        - {name: ids, in: path, required: true, schema: {type: array, items: {type: integer}}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Case"}
  /cases/{caseId}/name:
    post:
      operationId: renameCase
      parameters:
        - {name: caseId, in: path, required: true, schema: {type: string}}
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: "#/components/schemas/RenameCaseRequest"}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Case"}
  /lookup:
    get:
      operationId: lookupCases
      parameters:
        - {name: where, in: query, schema: {$ref: "#/components/schemas/Where"}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Case"}
  /search:
    get:
      operationId: searchCases
      parameters:
        - {name: filter, in: query, style: deepObject, schema: {type: object}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Case"}
  /upload:
    post:
      operationId: uploadFile
      requestBody:
        content:
          multipart/form-data:
            schema: {type: object, properties: {file: {type: string}}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Case"}
components:
  schemas:
    Case:
      type: object
      properties:
        caseId: {type: string}
        caseName: {type: string}
        owner: {$ref: "#/components/schemas/Owner"}
    CaseUpdate:
      type: object
      required: [version]
      properties:
        caseName: {type: string}
        note: {type: string, nullable: true}
        version: {type: integer, readOnly: true}
        owner: {$ref: "#/components/schemas/Owner"}
    Owner:
      type: object
      additionalProperties: true
      properties: {name: {type: string}}
    RenameCaseRequest:
      type: object
      required: [caseName]
      properties: {caseName: {type: string}}
    Where:
      type: object
      properties: {caseName: {type: string}}
"""


type RequestsFor = Callable[[list[str]], ModuleType]


@pytest.fixture
def requests_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RequestsFor:
    def generate(operation_ids: list[str]) -> ModuleType:
        spec = tmp_path / "spec.yml"
        spec.write_text(SPEC)
        output = tmp_path / "requests.py"
        generate_request_models(spec_path=spec, operation_ids=operation_ids, output=output)
        module = ModuleType("generated_requests")
        monkeypatch.setitem(sys.modules, module.__name__, module)
        exec(compile(output.read_text(), str(output), "exec"), module.__dict__)  # noqa: S102
        return module

    return generate


def model(module: ModuleType, name: str) -> type[BaseModel]:
    return cast(type[BaseModel], getattr(module, name))


def sent_by(operation_id: str, request: BaseModel, **headers: str) -> httpx2.Request:
    seen: list[httpx2.Request] = []

    def handler(sent: httpx2.Request) -> httpx2.Response:
        seen.append(sent)
        return httpx2.Response(200, json={"caseId": "c"})

    http = httpx2.AsyncClient(
        base_url="https://upstream.example/v3", transport=httpx2.MockTransport(handler)
    )
    client = OperationClient(cast(dict[str, object], yaml.safe_load(SPEC)), http)
    operation = Operation[dict[str, object], BaseModel](
        operation_id, TypeAdapter(dict[str, object])
    )
    asyncio.run(client.call(operation, request, headers=headers or None))
    return seen[0]


def test_a_request_takes_snake_case_names_and_sends_the_spec_names(
    requests_for: RequestsFor,
) -> None:
    generated = requests_for(["updateCase"])
    request = model(generated, "UpdateCaseRequest")(
        path=model(generated, "UpdateCasePath")(case_id="a/b"),
        query=model(generated, "UpdateCaseQuery")(screen_mode="SYNC", tags=["x", "y"]),
        body=model(generated, "CaseUpdateInput")(case_name="n"),
    )

    sent = sent_by("updateCase", request, **{"X-Trace": "t1"})

    assert (sent.method, sent.url.raw_path) == (
        "PATCH",
        b"/v3/cases/a%2Fb?screenMode=SYNC&tags=x&tags=y",
    )
    assert json.loads(sent.content) == {"caseName": "n"}
    assert sent.headers["x-trace"] == "t1"


def test_a_required_body_whose_fields_are_all_optional_is_sent_empty(
    requests_for: RequestsFor,
) -> None:
    generated = requests_for(["updateCase"])
    request = model(generated, "UpdateCaseRequest")(
        path=model(generated, "UpdateCasePath")(case_id="c"),
        body=model(generated, "CaseUpdateInput")(),
    )

    sent = sent_by("updateCase", request)

    assert sent.url.raw_path == b"/v3/cases/c"
    assert json.loads(sent.content) == {}


def test_a_body_field_set_to_none_is_sent_as_null(requests_for: RequestsFor) -> None:
    generated = requests_for(["updateCase"])
    request = model(generated, "UpdateCaseRequest")(
        path=model(generated, "UpdateCasePath")(case_id="c"),
        query=model(generated, "UpdateCaseQuery")(screen_mode=None),
        body=model(generated, "CaseUpdateInput")(note=None),
    )

    sent = sent_by("updateCase", request)

    assert sent.url.raw_path == b"/v3/cases/c"
    assert json.loads(sent.content) == {"note": None}


def test_a_request_body_leaves_out_the_read_only_fields(requests_for: RequestsFor) -> None:
    case_update = model(requests_for(["updateCase"]), "CaseUpdateInput")

    assert set(case_update.model_fields) == {"case_name", "note", "owner"}


def test_a_component_the_request_sends_is_named_as_an_input(requests_for: RequestsFor) -> None:
    generated = requests_for(["updateCase"])
    request = model(generated, "UpdateCaseRequest")(
        path=model(generated, "UpdateCasePath")(case_id="c"),
        body=model(generated, "CaseUpdateInput")(owner=model(generated, "OwnerInput")(name="o")),
    )

    sent = sent_by("updateCase", request)

    assert json.loads(sent.content) == {"owner": {"name": "o"}}
    assert not hasattr(generated, "CaseUpdate")
    assert not hasattr(generated, "Owner")


def test_a_component_named_like_a_request_model_is_sent_as_its_input(
    requests_for: RequestsFor,
) -> None:
    generated = requests_for(["renameCase"])
    request = model(generated, "RenameCaseRequest")(
        path=model(generated, "RenameCasePath")(case_id="c"),
        body=model(generated, "RenameCaseRequestInput")(case_name="n"),
    )

    sent = sent_by("renameCase", request)

    assert (sent.method, sent.url.raw_path) == ("POST", b"/v3/cases/c/name")
    assert json.loads(sent.content) == {"caseName": "n"}


def test_a_request_model_rejects_a_field_it_does_not_have(requests_for: RequestsFor) -> None:
    generated = requests_for(["updateCase"])

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model(generated, "UpdateCaseQuery")(screen_mod="SYNC")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model(generated, "UpdateCasePath").model_validate({"caseId": "c"})


@pytest.mark.parametrize("case_id", ["", ".", ".."])
def test_a_path_value_that_would_reach_another_endpoint_is_rejected(
    requests_for: RequestsFor, case_id: str
) -> None:
    generated = requests_for(["updateCase"])
    request = model(generated, "UpdateCaseRequest")(
        path=model(generated, "UpdateCasePath")(case_id=case_id),
        body=model(generated, "CaseUpdateInput")(),
    )

    with pytest.raises(ValueError, match=r"updateCase: path \['caseId'\] is empty, \. or \.\."):
        sent_by("updateCase", request)


def test_a_boolean_path_parameter_is_sent_in_lowercase(requests_for: RequestsFor) -> None:
    generated = requests_for(["setFlag"])
    request = model(generated, "SetFlagRequest")(path=model(generated, "SetFlagPath")(enabled=True))

    assert sent_by("setFlag", request).url.raw_path == b"/v3/flags/true"


def test_a_request_needs_its_path_and_its_required_body(requests_for: RequestsFor) -> None:
    generated = requests_for(["updateCase"])

    with pytest.raises(ValidationError) as missing:
        model(generated, "UpdateCaseRequest")()

    assert {error["loc"] for error in missing.value.errors()} == {("path",), ("body",)}


def test_a_body_written_in_place_gets_a_model_that_keeps_the_spec_bounds(
    requests_for: RequestsFor,
) -> None:
    body = model(requests_for(["createCase"]), "CreateCaseBody")

    assert body(case_name="short").model_dump(by_alias=True) == {"caseName": "short"}
    with pytest.raises(ValidationError, match="at most 5 characters"):
        body(case_name="too long")


@pytest.mark.parametrize(
    ("operation_id", "reason"),
    [
        ("searchCases", "the query parameter filter uses the deepObject style"),
        ("getReports", "the path parameter ids is not a single value"),
        ("lookupCases", "the query parameter where is not a single value or a list of them"),
        ("uploadFile", "the request body is not JSON"),
    ],
)
def test_an_operation_the_typed_call_cannot_send_gets_no_request_model(
    tmp_path: Path, operation_id: str, reason: str
) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    output = tmp_path / "requests.py"

    untyped = generate_request_models(
        spec_path=spec, operation_ids=["updateCase", operation_id], output=output
    )

    assert untyped == {operation_id: reason}
    generated = output.read_text()
    assert "class UpdateCaseRequest(RequestModel):" in generated
    assert f"class {operation_id[0].upper()}{operation_id[1:]}Request(" not in generated


def test_a_requests_module_without_a_typed_operation_is_still_written(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    output = tmp_path / "requests.py"

    untyped = generate_request_models(spec_path=spec, operation_ids=["uploadFile"], output=output)

    assert untyped == {"uploadFile": "the request body is not JSON"}
    assert output.read_text().startswith("# generated by mcp_openapi.codegen")


def test_each_operation_constant_carries_its_request_model(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    output = tmp_path / "operations.py"

    generate_operations(
        spec_path=spec,
        operation_ids=["updateCase", "uploadFile"],
        operation_module="mcp_openapi.upstream",
        models_module="models",
        requests_module="requests",
        output=output,
    )

    generated = output.read_text()
    assert (
        'UPDATE_CASE = Operation[Case, UpdateCaseRequest]("updateCase", TypeAdapter(Case))\n'
    ) in generated
    assert (
        "# call_untyped only: the request body is not JSON\n"
        'UPLOAD_FILE = Operation[Case]("uploadFile", TypeAdapter(Case))\n'
    ) in generated
    assert "from requests import UpdateCaseRequest\n" in generated


def test_the_type_check_rejects_a_wrong_field_a_missing_body_and_another_request(
    tmp_path: Path, requests_for: RequestsFor
) -> None:
    requests_for(["updateCase"])
    usage = [
        "from mcp_openapi.upstream import Operation, OperationClient",
        "from pydantic import TypeAdapter",
        "from requests import CaseUpdateInput, UpdateCasePath, UpdateCaseRequest",
        "",
        'UPDATE_CASE = Operation[object, UpdateCaseRequest]("updateCase", TypeAdapter(object))',
        "",
        'UpdateCaseRequest(path=UpdateCasePath(case_id="c"), body=CaseUpdateInput())',
        'UpdateCaseRequest(path=UpdateCasePath(case_id="c"))',
        'UpdateCasePath(caseId="c")',
        "",
        "async def call_with_another_request(upstream: OperationClient) -> None:",
        "    _ = await upstream.call(UPDATE_CASE, CaseUpdateInput())",
    ]
    (tmp_path / "usage.py").write_text("\n".join([*usage, ""]))

    checked = subprocess.run(
        [str(Path(sys.executable).parent / "basedpyright"), "--pythonpath", sys.executable],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    errors = [
        line for line in checked.stdout.splitlines() if "usage.py:" in line and "error" in line
    ]
    assert len(errors) == 4, checked.stdout
    assert 'usage.py:8:1 - error: Argument missing for parameter "body"' in checked.stdout
    assert 'usage.py:9:16 - error: No parameter named "caseId"' in checked.stdout
    assert any(
        "usage.py:12:" in line and 'cannot be assigned to parameter "operation"' in line
        for line in errors
    ), checked.stdout


def test_models_with_additional_properties_pass_the_strictest_type_check(
    tmp_path: Path, requests_for: RequestsFor
) -> None:
    requests_for(["updateCase"])
    generate_response_models(
        spec_path=tmp_path / "spec.yml",
        operation_ids=["updateCase"],
        output=tmp_path / "responses.py",
    )
    (tmp_path / "pyrightconfig.json").write_text(
        json.dumps({"typeCheckingMode": "all", "include": ["requests.py", "responses.py"]})
    )

    checked = subprocess.run(
        [str(Path(sys.executable).parent / "basedpyright"), "--pythonpath", sys.executable],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert "0 errors" in checked.stdout, checked.stdout


def test_the_requests_module_and_its_output_are_configured_together() -> None:
    with pytest.raises(ValidationError, match="requests-module and requests-output go together"):
        CodegenConfig.model_validate(
            {
                "spec": "spec.yml",
                "operation-ids": ["updateCase"],
                "operation-module": "mcp_openapi.upstream",
                "models-module": "models",
                "models-output": "models.py",
                "requests-module": "requests",
                "operations-output": "operations.py",
            }
        )
