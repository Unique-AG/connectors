from typing import ClassVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    model_serializer,
)


class OmitNoneModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    @model_serializer(mode="wrap")
    def _omit_none(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        serialized = cast("object", handler(self))
        assert isinstance(serialized, dict)
        return {
            key: value
            for key, value in cast("dict[str, object]", serialized).items()
            if value is not None
        }


def published_output_schema(annotation: object) -> dict[str, object]:
    raw = cast("object", TypeAdapter(annotation).json_schema(mode="validation"))
    assert isinstance(raw, dict)
    schema = {str(key): value for key, value in cast("dict[object, object]", raw).items()}
    if schema.get("type") == "object" or "properties" in schema:
        return schema
    return {"type": "object", **schema}
