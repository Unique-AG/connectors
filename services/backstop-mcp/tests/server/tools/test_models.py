"""`OmitNoneModel` and `published_output_schema`: omitted nulls, documented in the schema."""

from typing import cast

import pytest
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools import tool
from fastmcp.tools.function_tool import FunctionTool, ToolMeta
from pydantic import Field, TypeAdapter, ValidationError

from backstop_mcp.models import CoercedId, OmitNoneModel, coerce_ids, published_output_schema


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


def test_coerced_id_accepts_a_json_number() -> None:
    assert TypeAdapter(CoercedId).validate_python(8746199) == "8746199"
    assert TypeAdapter(list[CoercedId]).validate_python([8746199, "202"]) == ["8746199", "202"]


def test_coerced_id_strips_surrounding_whitespace() -> None:
    assert TypeAdapter(CoercedId).validate_python("  8746199  ") == "8746199"


@pytest.mark.parametrize("blank", ["", "   "])
def test_coerced_id_rejects_a_blank_value(blank: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CoercedId).validate_python(blank)


def test_coerce_ids_stringifies_json_numbers() -> None:
    assert coerce_ids([8746199, "202"]) == ("8746199", "202")


def test_coerce_ids_strips_and_drops_blank_entries() -> None:
    assert coerce_ids([8746199, "  ", "", "202", "  3  "]) == ("8746199", "202", "3")
