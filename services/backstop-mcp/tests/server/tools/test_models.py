"""`OmitNoneModel` and `published_output_schema`: omitted nulls, documented in the schema."""

from typing import cast

import pytest
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools import tool
from fastmcp.tools.function_tool import FunctionTool, ToolMeta
from pydantic import Field

from backstop_mcp.models import OmitNoneModel, published_output_schema


class _Payload(OmitNoneModel):
    kept: str
    dropped: str | None = Field(
        default=None, description="A nullable field that serializes omitted."
    )


@tool(output_schema=published_output_schema(_Payload))
async def _echo_payload() -> _Payload:
    return _Payload(kept="value")


def _schema(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_dump_omits_none_keys() -> None:
    assert _Payload(kept="value").model_dump() == {"kept": "value"}


def test_published_schema_still_documents_the_nullable_field() -> None:
    schema = published_output_schema(_Payload)
    dropped = _schema(_schema(schema["properties"])["dropped"])

    assert "A nullable field that serializes omitted." in str(dropped)


def test_the_decorated_tool_publishes_that_schema() -> None:
    meta = get_fastmcp_meta(_echo_payload)
    assert isinstance(meta, ToolMeta)
    schema = _schema(meta.output_schema)
    dropped = _schema(_schema(schema["properties"])["dropped"])

    assert "A nullable field that serializes omitted." in str(dropped)


@pytest.mark.asyncio
async def test_structured_content_omits_the_null_key() -> None:
    meta = get_fastmcp_meta(_echo_payload)
    assert isinstance(meta, ToolMeta)
    function_tool = FunctionTool.from_function(_echo_payload, metadata=meta)

    result = await function_tool.run({})

    assert result.structured_content == {"kept": "value"}
