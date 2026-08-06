"""Helpers for asserting MCP `CallToolResult` payloads in tool tests."""

from __future__ import annotations

import json
from typing import cast

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, TypeAdapter


def tool_payload(result: CallToolResult) -> dict[str, object]:
    assert isinstance(result, CallToolResult)
    assert result.isError is not True
    assert result.content, "expected non-empty CallToolResult.content"
    block = result.content[0]
    assert isinstance(block, TextContent)
    payload = cast(object, json.loads(block.text))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def tool_model[T: BaseModel](result: CallToolResult, model: type[T]) -> T:
    return model.model_validate(tool_payload(result))


def tool_model_union(result: CallToolResult, union: object) -> BaseModel:
    """Validate against a PEP 604 / typing union of response models."""
    return cast(BaseModel, TypeAdapter(union).validate_python(tool_payload(result)))
