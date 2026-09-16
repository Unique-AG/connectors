from typing import ClassVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    model_serializer,
)


class OmitNoneModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    @model_serializer(mode="wrap")
    def serialize_without_none(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        serialized = cast("object", handler(self))
        assert isinstance(serialized, dict)
        return {
            key: value
            for key, value in cast("dict[str, object]", serialized).items()
            if value is not None
        }
