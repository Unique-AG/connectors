"""Shared pydantic bases used by tool-facing response models."""

from typing import cast

from pydantic import BaseModel, SerializerFunctionWrapHandler, TypeAdapter, model_serializer


class OmitNoneModel(BaseModel):
    """Drop `None`-valued keys when this model is serialized.

    Absent versus null is a property of *this* model's fields: a key that is not present means
    there is no value, not that the value is the JSON null. Nested models that do not inherit
    this keep their nulls — it is not a substitute for `exclude_none=True` over a whole tree.

    A wrap serializer that returns a dict erases pydantic's serialization JSON schema, so a
    tool whose return type uses this base must pass `output_schema=published_output_schema(...)`
    (the validation schema still lists every field, including ones omitted when null).
    """

    @model_serializer(mode="wrap")
    def _omit_none(self, serializer: SerializerFunctionWrapHandler) -> dict[str, object]:
        dumped: object = serializer(self)  # pyright: ignore[reportAny]
        assert isinstance(dumped, dict)
        items = {str(key): value for key, value in cast("dict[object, object]", dumped).items()}
        return {key: value for key, value in items.items() if value is not None}


def published_output_schema(annotation: object) -> dict[str, object]:
    """JSON Schema FastMCP can publish for a tool return type.

    Uses validation mode so `OmitNoneModel` fields survive: its wrap serializer returns a dict
    and pydantic then has no serialization schema to publish. MCP also requires a root object,
    so a union of models (`anyOf` / `oneOf` at the root) is labelled as one.
    """
    raw: object = TypeAdapter(annotation).json_schema(mode="validation")
    assert isinstance(raw, dict)
    schema = {str(key): value for key, value in cast("dict[object, object]", raw).items()}
    if schema.get("type") == "object" or "properties" in schema:
        return schema
    return {"type": "object", **schema}
