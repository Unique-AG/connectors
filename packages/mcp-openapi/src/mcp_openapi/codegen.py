import json
import re
import subprocess
import sys
from collections.abc import Collection, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import httpx2
import yaml
from openapi_pydantic.v3.v3_0 import DataType, OpenAPI, Reference, Response, Schema
from openapi_pydantic.v3.v3_0 import Operation as OpenApiOperation

from mcp_openapi.openapi import mcp_name

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
    kept = {key: properties[key] for key in fields[name]}
    return node.model_copy(update={"properties": kept, "additionalProperties": None})


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
        raw = cast(object, yaml.safe_load(_read_spec(spec_path, spec_url, client)))
    except yaml.YAMLError as exc:
        raise ValueError(f"the spec is not valid YAML or JSON: {exc}") from exc
    spec = cast(dict[str, object], raw) if isinstance(raw, dict) else {}
    # potentially extendable with an extra import of 3.1 specs
    version = str(spec.get("openapi", ""))
    if not version.startswith("3.0"):
        raise ValueError(
            f"only OpenAPI 3.0 specs are supported, got {version or 'no openapi field'}"
        )
    return spec


def generate_response_models(
    *,
    spec_path: Path | None = None,
    spec_url: str | None = None,
    client: httpx2.Client | None = None,
    operation_ids: Collection[str],
    fields: Mapping[str, tuple[str, ...]] | None = None,
    allow_extra_fields: bool = False,
    output: Path,
) -> None:
    """Write pydantic models for the responses of `operation_ids`, trimmed to `fields` per model.

    With `allow_extra_fields` the models keep fields the spec does not declare, so a field cut by
    `fields` stays in the data as an untyped extra and only the schema is trimmed.

    The spec is read from `spec_path` or fetched from `spec_url`, with `client` if given.
    """
    spec = OpenAPI.model_validate(_load_spec(spec_path, spec_url, client))
    declared = (spec.components.schemas if spec.components else None) or {}
    operations = _selected_operations(spec, operation_ids)
    inline = _inline_models(operations, spec)
    clashes = inline.keys() & declared.keys()
    assert not clashes, f"components.schemas already has {sorted(clashes)}"
    names = sorted(_response_schema_names(operations.values(), spec))
    if not names and not inline:
        raise ValueError("none of the operations has a response schema to generate a model from")
    trimmed = fields or {}
    unknown = trimmed.keys() - {*names, *inline}
    assert not unknown, f"fields name models that are not generated: {sorted(unknown)}"
    schemas = {**{name: declared[name] for name in names}, **inline}
    selected = {
        name: _slim(name, _clean(schema), trimmed).model_dump(
            by_alias=True, exclude_none=True, mode="json"
        )
        for name, schema in schemas.items()
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
        extra_fields = ["--extra-fields", "allow"] if allow_extra_fields else []
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
                *extra_fields,
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


def _inline_model_name(operation_id: str) -> str:
    words = re.split(r"[^A-Za-z0-9]+", operation_id)
    return "".join(word[:1].upper() + word[1:] for word in words if word) + "Response"


def _inline_response(operation: OpenApiOperation, spec: OpenAPI) -> Schema | None:
    """The success response when it is an object with fields, or allOf, oneOf, anyOf, in place."""
    schema = _response_schema(operation, spec)
    if not isinstance(schema, Schema):
        return None
    composed = schema.allOf or schema.oneOf or schema.anyOf
    described = schema.properties or schema.additionalProperties
    return schema if schema.type in (None, DataType.OBJECT) and (composed or described) else None


def _inline_models(operations: Mapping[str, OpenApiOperation], spec: OpenAPI) -> dict[str, Schema]:
    models: dict[str, Schema] = {}
    for operation_id, operation in operations.items():
        schema = _inline_response(operation, spec)
        if schema is None:
            continue
        name = _inline_model_name(operation_id)
        assert operation_id.isascii(), f"{operation_id!r} has characters a name would lose"
        assert name != "Response", f"{operation_id!r} has no letters or digits to name a model by"
        assert name.isidentifier(), f"{operation_id} would make the invalid model name {name!r}"
        assert name not in models, f"two operationIds make the model name {name}"
        models[name] = schema
    return models


def _response_model(
    operation_id: str, operation: OpenApiOperation, spec: OpenAPI
) -> tuple[str, bool]:
    """The model name of the success response, and whether the body is an array of it."""
    if _inline_response(operation, spec):
        return _inline_model_name(operation_id), False
    schema = _response_schema(operation, spec)
    if schema is None:
        raise ValueError(f"{operation_id}: the success response has no JSON body")
    items = schema.items if isinstance(schema, Schema) and schema.type == DataType.ARRAY else None
    target = items or schema
    if not isinstance(target, Reference):
        problem = "is not an object with fields, a named schema or an array of one"
        raise ValueError(f"{operation_id}: the success response {problem}")
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
    return mcp_name(operation_id).upper()


def _constant(name: str, operation_id: str, model: str, is_array: bool) -> str:
    body = f"list[{model}]" if is_array else model
    # Some checkers infer `Operation[Unknown]` from the `TypeAdapter` alone.
    return f"{name} = Operation[{body}]({json.dumps(operation_id)}, TypeAdapter({body}))"


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
    ascii_only = all(operation_id.isascii() for operation_id in responses)
    assert ascii_only, "an operationId has characters that a constant name would lose"
    names = {operation_id: _constant_name(operation_id) for operation_id in responses}
    invalid = sorted(oid for oid, name in names.items() if not name.isidentifier())
    assert not invalid, f"operationIds that make an invalid constant name: {invalid}"
    assert len(set(names.values())) == len(names), "two operationIds make the same constant name"
    constants = "\n".join(
        _constant(names[operation_id], operation_id, model, is_array)
        for operation_id, (model, is_array) in responses.items()
    )
    models = ", ".join(sorted({model for model, _ in responses.values()}))
    imports = "\n".join(
        sorted(
            [f"from {operation_module} import Operation", f"from {models_module} import {models}"]
        )
    )
    header = "# generated by mcp_openapi.codegen\nfrom pydantic import TypeAdapter\n\n"
    output.write_text(f"{header}{imports}\n\n{constants}\n")
    for command in (["check", "--select", "I", "--fix", "--quiet"], ["format"]):
        subprocess.run([sys.executable, "-m", "ruff", *command, str(output)], check=True)
