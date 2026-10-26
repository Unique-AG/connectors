"""Helpers for asserting tool return values in tests.

Tools return pydantic models directly. `tool_payload` dumps them the way FastMCP serializes
`structuredContent`, so tests that pin absent-versus-null can still see omitted keys.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from fastmcp.server.dependencies import without_injected_parameters
from pydantic import BaseModel, TypeAdapter

if TYPE_CHECKING:
    from typing_extensions import TypeForm


def object_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def object_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast(list[object], value)


def tool_payload(result: BaseModel) -> dict[str, object]:
    return object_dict(result.model_dump(mode="json"))


def tool_model[T: BaseModel](result: object, model: type[T]) -> T:
    assert isinstance(result, model)
    return result


def tool_model_union(result: object, union: object) -> BaseModel:
    """Validate against a PEP 604 / typing union of response models."""
    assert isinstance(result, BaseModel)
    return cast(BaseModel, TypeAdapter(cast("TypeForm[object]", union)).validate_python(result))


def input_adapter(tool: Callable[..., object]) -> TypeAdapter[object]:
    """The adapter of the arguments a client passes `tool`, without those FastMCP injects."""
    return TypeAdapter(cast("TypeForm[object]", without_injected_parameters(tool)))
