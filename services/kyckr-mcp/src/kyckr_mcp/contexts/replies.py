from typing import cast, ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_serializer
from pydantic import SerializerFunctionWrapHandler
from pydantic.alias_generators import to_camel

_EXACT_FLOAT_LIMIT = 2**53


class KyckrModel(BaseModel):
    """Read from Kyckr's model by attribute, and written with Kyckr's camelCase names."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        alias_generator=to_camel,
        serialize_by_alias=True,
        validate_by_name=True,
        from_attributes=True,
    )


class Cost(KyckrModel):
    """A price in Kyckr credits."""

    type: str | None = Field(None, description="The unit of `value`, such as `credit`.")
    value: float | None = Field(None, description="The amount.")


class Reply(KyckrModel):
    """What every tool answers with. Empty fields are left out, and a whole number stays a whole
    number.
    """

    correlation_id: str | None = Field(
        None, description="Kyckr's id for the request, to quote to its support."
    )
    details: str | None = Field(None, description="Kyckr's status details for the request.")
    cost: Cost | None = Field(None, description="What this call cost.")

    @model_serializer(mode="wrap")
    def _omit_empty_fields(self, handler: SerializerFunctionWrapHandler):  # noqa: ANN202
        # No return annotation: one would replace the output schema FastMCP publishes.
        return _tidy(cast("object", handler(self)))


def _tidy(value: object) -> object:
    """Drops None and turns a whole float below 2**53 into an int, as the old service printed it."""
    if isinstance(value, dict):
        fields = cast(dict[str, object], value)
        return {key: _tidy(item) for key, item in fields.items() if item is not None}
    if isinstance(value, list):
        return [_tidy(item) for item in cast(list[object], value)]
    if isinstance(value, float) and value.is_integer() and abs(value) < _EXACT_FLOAT_LIMIT:
        return int(value)
    return value
