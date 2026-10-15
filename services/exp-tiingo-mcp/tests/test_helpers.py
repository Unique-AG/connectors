from pathlib import Path

import httpx2
import pytest

from tiingo_mcp.helpers.codegen import generate_response_models

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
