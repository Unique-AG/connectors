import json
import re
import subprocess
import sys
from collections.abc import Collection, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx2
import yaml
from openapi_pydantic.v3.v3_0 import DataType, OpenAPI, Reference, Response, Schema
from openapi_pydantic.v3.v3_0 import Operation as OpenApiOperation

# Schema fields that constrain input. Responses keep wire-format values as they are.
_DROPPED = dict.fromkeys(
    [
        "example",
        "discriminator",
        "schema_format",
        "maxLength",
        "minLength",
        "pattern",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "enum",
        "default",
    ]
)


def _clean_all(nodes: list[Reference | Schema] | None) -> list[Reference | Schema] | None:
    return None if nodes is None else [_clean(node) for node in nodes]


def _clean(node: Reference | Schema) -> Reference | Schema:
    if isinstance(node, Reference):
        return node
    extensions = dict.fromkeys(
        key for key in node.model_extra or {} if key.startswith("x-") or key == "examples"
    )
    properties = node.properties
    additional = node.additionalProperties
    return node.model_copy(
        update={
            **_DROPPED,
            **extensions,
            "properties": None
            if properties is None
            else {name: _clean(prop) for name, prop in properties.items()},
            "items": None if node.items is None else _clean(node.items),
            "allOf": _clean_all(node.allOf),
            "oneOf": _clean_all(node.oneOf),
            "anyOf": _clean_all(node.anyOf),
            "schema_not": None if node.schema_not is None else _clean(node.schema_not),
            "additionalProperties": _clean(additional)
            if isinstance(additional, Reference | Schema)
            else additional,
        }
    )


def _slim(
    name: str, node: Reference | Schema, fields: Mapping[str, tuple[str, ...]]
) -> Reference | Schema:
    if name not in fields:
        return node
    assert isinstance(node, Schema), f"{name} is a reference, not a schema"
    properties = node.properties or {}
    missing = set(fields[name]) - properties.keys()
    assert not missing, f"{name}: spec has no {sorted(missing)}"
    return node.model_copy(update={"properties": {key: properties[key] for key in fields[name]}})


def _read_spec(spec_path: Path | None, spec_url: str | None, client: httpx2.Client | None) -> str:
    assert (spec_path is None) != (spec_url is None), "pass exactly one of spec_path and spec_url"
    if spec_path is not None:
        return spec_path.read_text()
    assert spec_url is not None
    response = client.get(spec_url) if client else httpx2.get(spec_url, follow_redirects=True)
    response.raise_for_status()
    return response.text


def _load_spec(
    spec_path: Path | None, spec_url: str | None, client: httpx2.Client | None
) -> dict[str, object]:
    try:
        raw = yaml.safe_load(_read_spec(spec_path, spec_url, client))
    except yaml.YAMLError as exc:
        raise ValueError(f"the spec is not valid YAML or JSON: {exc}") from exc
    # potentially extendable with an extra import of 3.1 specs
    version = str(raw.get("openapi", "")) if isinstance(raw, dict) else ""
    if not version.startswith("3.0"):
        raise ValueError(
            f"only OpenAPI 3.0 specs are supported, got {version or 'no openapi field'}"
        )
    return raw


def generate_response_models(
    *,
    spec_path: Path | None = None,
    spec_url: str | None = None,
    client: httpx2.Client | None = None,
    operation_ids: Collection[str],
    fields: Mapping[str, tuple[str, ...]],
    output: Path,
) -> None:
    """Write pydantic models for the responses of `operation_ids`, trimmed to `fields` per model.

    The spec is read from `spec_path` or fetched from `spec_url`, with `client` if given.
    """
    spec = OpenAPI.model_validate(_load_spec(spec_path, spec_url, client))
    components = spec.components
    if not (components and components.schemas):
        raise ValueError("the spec has no components.schemas")
    operations = _selected_operations(spec, operation_ids)
    names = sorted(_response_schema_names(operations.values(), spec))
    if not names:
        raise ValueError("none of the operations has a named response schema")
    unknown = fields.keys() - set(names)
    assert not unknown, f"fields name models that are not generated: {sorted(unknown)}"
    selected = {
        name: _slim(name, _clean(components.schemas[name]), fields).model_dump(
            by_alias=True, exclude_none=True, mode="json"
        )
        for name in names
    }
    with TemporaryDirectory() as directory:
        source = Path(directory) / "responses.json"
        source.write_text(
            json.dumps(
                {
                    "openapi": "3.0.3",
                    "info": {"title": "Responses", "version": "1"},
                    "paths": {},
                    "components": {"schemas": selected},
                }
            )
        )
        subprocess.run(
            [
                sys.executable, "-m", "datamodel_code_generator",
                "--input", str(source),
                "--input-file-type", "openapi",
                "--output", str(output),
                "--output-model-type", "pydantic_v2.BaseModel",
                "--target-python-version", "3.12",
                "--use-union-operator",
                "--use-standard-collections",
                "--collapse-root-models",
                "--disable-timestamp",
                "--custom-file-header", "# generated by datamodel-codegen\n# ruff: noqa: E501",
                "--formatters", "ruff-check", "ruff-format",
            ],
            check=True,
        )  # fmt: skip


def _selected_operations(
    spec: OpenAPI, operation_ids: Collection[str]
) -> dict[str, OpenApiOperation]:
    operations = {
        operation.operationId: operation
        for item in (spec.paths or {}).values()
        for operation in (
            item.get, item.put, item.post, item.delete,
            item.options, item.head, item.patch, item.trace,
        )
        if operation and operation.operationId
    }  # fmt: skip
    missing = set(operation_ids) - operations.keys()
    assert not missing, f"operationIds not in the spec: {sorted(missing)}"
    return {operation_id: operations[operation_id] for operation_id in operation_ids}


def _response_schema(operation: OpenApiOperation, spec: OpenAPI) -> Reference | Schema | None:
    code = min((code for code in operation.responses if code.startswith("2")), default="")
    response = operation.responses.get(code)
    if isinstance(response, Reference):
        responses = spec.components.responses if spec.components else None
        response = (responses or {}).get(_ref_name(response))
    if not isinstance(response, Response):
        return None
    media = next(
        (media for kind, media in (response.content or {}).items() if "json" in kind), None
    )
    return media.media_type_schema if media else None


def _ref_name(ref: Reference) -> str:
    return ref.ref.rsplit("/", 1)[-1]


def _response_model(
    operation_id: str, operation: OpenApiOperation, spec: OpenAPI
) -> tuple[str, bool]:
    """The model name of the success response, and whether the body is an array of it."""
    schema = _response_schema(operation, spec)
    items = schema.items if isinstance(schema, Schema) and schema.type == DataType.ARRAY else None
    target = items or schema
    if not isinstance(target, Reference):
        raise ValueError(
            f"{operation_id}: the success response is not a named schema or an array of one"
        )
    return _ref_name(target), items is not None


def _referenced_names(node: Reference | Schema | bool | None) -> list[str]:
    """Names of the schemas `node` refers to directly, at any depth of its inline parts."""
    if isinstance(node, Reference):
        return [_ref_name(node)]
    if not isinstance(node, Schema):
        return []
    children = [
        *(node.properties or {}).values(),
        node.items,
        node.schema_not,
        node.additionalProperties,
        *(node.allOf or []),
        *(node.oneOf or []),
        *(node.anyOf or []),
    ]
    return [name for child in children for name in _referenced_names(child)]


def _response_schema_names(operations: Collection[OpenApiOperation], spec: OpenAPI) -> set[str]:
    """Every component schema the responses of `operations` reach, nested ones included."""
    schemas = spec.components.schemas if spec.components and spec.components.schemas else {}
    found: set[str] = set()
    pending = [
        name
        for operation in operations
        for name in _referenced_names(_response_schema(operation, spec))
    ]
    while pending:
        name = pending.pop()
        if name not in found:
            assert name in schemas, f"{name} is referenced but not in components.schemas"
            found.add(name)
            pending.extend(_referenced_names(schemas[name]))
    return found


def _constant_name(operation_id: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", operation_id).upper()


def generate_operations(
    *,
    spec_path: Path | None = None,
    spec_url: str | None = None,
    client: httpx2.Client | None = None,
    operation_ids: Collection[str],
    operation_module: str,
    models_module: str,
    output: Path,
) -> None:
    """Write an `Operation` constant per operationId, typed with its model from `models_module`.

    `operation_module` is where `Operation` is imported from.
    """
    spec = OpenAPI.model_validate(_load_spec(spec_path, spec_url, client))
    responses = {
        operation_id: _response_model(operation_id, operation, spec)
        for operation_id, operation in _selected_operations(spec, operation_ids).items()
    }
    constants = "\n".join(
        f'{_constant_name(operation_id)} = Operation("{operation_id}", '
        f"TypeAdapter({f'list[{model}]' if is_array else model}))"
        for operation_id, (model, is_array) in responses.items()
    )
    models = ", ".join(sorted({model for model, _ in responses.values()}))
    imports = "\n".join(
        sorted(
            [f"from {operation_module} import Operation", f"from {models_module} import {models}"]
        )
    )
    output.write_text(
        "# generated by tiingo_mcp.helpers.codegen\n"
        "from pydantic import TypeAdapter\n\n"
        f"{imports}\n\n"
        f"{constants}\n"
    )
    subprocess.run([sys.executable, "-m", "ruff", "format", str(output)], check=True)
