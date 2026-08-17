"""Helpers for asserting tool return values in tests.

Tools return pydantic models directly. `tool_payload` dumps them the way FastMCP serializes
`structuredContent`, so tests that pin absent-versus-null can still see omitted keys.
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, TypeAdapter


def object_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def tool_payload(result: BaseModel) -> dict[str, object]:
    return object_dict(result.model_dump(mode="json"))


def tool_model[T: BaseModel](result: object, model: type[T]) -> T:
    assert isinstance(result, model)
    return result


def tool_model_union(result: object, union: object) -> BaseModel:
    """Validate against a PEP 604 / typing union of response models."""
    assert isinstance(result, BaseModel)
    return cast(BaseModel, TypeAdapter(union).validate_python(result))
