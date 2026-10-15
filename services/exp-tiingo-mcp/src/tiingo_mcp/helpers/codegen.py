import json
import subprocess
import sys
from collections.abc import Collection, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx2
import yaml
from fastmcp.utilities.openapi import parse_openapi_to_http_routes
from openapi_pydantic.v3.v3_0 import OpenAPI, Reference, Schema

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
    components = OpenAPI.model_validate(raw).components
    if not (components and components.schemas):
        raise ValueError("the spec has no components.schemas")
    routes = {route.operation_id: route for route in parse_openapi_to_http_routes(raw)}
    missing = set(operation_ids) - routes.keys()
    assert not missing, f"operationIds not in the spec: {sorted(missing)}"
    names = sorted(
        {name for operation_id in operation_ids for name in routes[operation_id].response_schemas}
    )
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
