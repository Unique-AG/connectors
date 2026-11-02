import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

import httpx2
import pytest
import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from mcp_openapi.cli import CodegenConfig
from mcp_openapi.codegen import generate_operations, generate_request_models
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
      properties: {caseId: {type: string}, caseName: {type: string}}
    CaseUpdate:
      type: object
      properties: {caseName: {type: string}, note: {type: string}}
"""


def requests_for(tmp_path: Path, operation_ids: list[str]) -> ModuleType:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    output = tmp_path / "requests.py"
    generate_request_models(spec_path=spec, operation_ids=operation_ids, output=output)
    module = ModuleType("generated_requests")
    sys.modules[module.__name__] = module
    exec(compile(output.read_text(), str(output), "exec"), module.__dict__)  # noqa: S102
    return module


def model(module: ModuleType, name: str) -> type[BaseModel]:
    return cast(type[BaseModel], getattr(module, name))


def sent_by(request_model: type[BaseModel], request: BaseModel, **headers: str) -> httpx2.Request:
    seen: list[httpx2.Request] = []

    def handler(sent: httpx2.Request) -> httpx2.Response:
        seen.append(sent)
        return httpx2.Response(200, json={"caseId": "c"})

    http = httpx2.AsyncClient(
        base_url="https://upstream.example/v3", transport=httpx2.MockTransport(handler)
    )
    client = OperationClient(cast(dict[str, object], yaml.safe_load(SPEC)), http)
    operation = Operation("updateCase", TypeAdapter(dict[str, object]), request_model)
    asyncio.run(client.call(operation, request, headers=headers or None))
    return seen[0]


def test_a_request_takes_snake_case_names_and_sends_the_spec_names(tmp_path: Path) -> None:
    generated = requests_for(tmp_path, ["updateCase"])
    request_model = model(generated, "UpdateCaseRequest")
    request = request_model(
        path=model(generated, "UpdateCasePath")(case_id="a/b"),
        query=model(generated, "UpdateCaseQuery")(screen_mode="SYNC", tags=["x", "y"]),
        body=model(generated, "CaseUpdate")(case_name="n"),
    )

    sent = sent_by(request_model, request, **{"X-Trace": "t1"})

    assert (sent.method, sent.url.raw_path) == (
        "PATCH",
        b"/v3/cases/a%2Fb?screenMode=SYNC&tags=x&tags=y",
    )
    assert json.loads(sent.content) == {"caseName": "n"}
    assert sent.headers["x-trace"] == "t1"


def test_a_required_body_whose_fields_are_all_optional_is_sent_empty(tmp_path: Path) -> None:
    generated = requests_for(tmp_path, ["updateCase"])
    request_model = model(generated, "UpdateCaseRequest")
    request = request_model(
        path=model(generated, "UpdateCasePath")(case_id="c"), body=model(generated, "CaseUpdate")()
    )

    sent = sent_by(request_model, request)

    assert sent.url.raw_path == b"/v3/cases/c"
    assert json.loads(sent.content) == {}


def test_a_request_needs_its_path_and_its_required_body(tmp_path: Path) -> None:
    generated = requests_for(tmp_path, ["updateCase"])

    with pytest.raises(ValidationError) as missing:
        model(generated, "UpdateCaseRequest")()

    assert {error["loc"] for error in missing.value.errors()} == {("path",), ("body",)}


def test_a_body_written_in_place_gets_a_model_that_keeps_the_spec_bounds(tmp_path: Path) -> None:
    body = model(requests_for(tmp_path, ["createCase"]), "CreateCaseBody")

    assert body(case_name="short").model_dump(by_alias=True) == {"caseName": "short"}
    with pytest.raises(ValidationError, match="at most 5 characters"):
        body(case_name="too long")


@pytest.mark.parametrize(
    ("operation_id", "problem"),
    [
        ("searchCases", r"searchCases: query parameters \['filter'\] use a style call cannot send"),
        ("uploadFile", "uploadFile: the request body is not JSON"),
    ],
)
def test_an_operation_the_typed_call_cannot_send_is_refused(
    tmp_path: Path, operation_id: str, problem: str
) -> None:
    with pytest.raises(ValueError, match=problem):
        requests_for(tmp_path, [operation_id])


def test_each_operation_constant_carries_its_request_model(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    output = tmp_path / "operations.py"

    generate_operations(
        spec_path=spec,
        operation_ids=["updateCase"],
        operation_module="mcp_openapi.upstream",
        models_module="models",
        requests_module="requests",
        output=output,
    )

    generated = output.read_text()
    assert (
        'UPDATE_CASE = Operation[Case, UpdateCaseRequest]("updateCase", TypeAdapter(Case), '
        "UpdateCaseRequest)"
    ) in generated
    assert "from requests import UpdateCaseRequest\n" in generated


def test_the_type_check_rejects_a_wrong_field_and_a_missing_body(tmp_path: Path) -> None:
    requests_for(tmp_path, ["updateCase"])
    usage = [
        "from requests import CaseUpdate, UpdateCasePath, UpdateCaseRequest",
        "",
        'UpdateCaseRequest(path=UpdateCasePath(case_id="c"), body=CaseUpdate())',
        'UpdateCaseRequest(path=UpdateCasePath(case_id="c"))',
        'UpdateCasePath(caseId="c")',
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
    assert len(errors) == 3, checked.stdout
    assert 'usage.py:4:1 - error: Argument missing for parameter "body"' in checked.stdout
    assert 'usage.py:5:16 - error: No parameter named "caseId"' in checked.stdout


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
