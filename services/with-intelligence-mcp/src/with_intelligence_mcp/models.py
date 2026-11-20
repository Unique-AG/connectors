from typing import TYPE_CHECKING, ClassVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    model_serializer,
)

if TYPE_CHECKING:
    from typing_extensions import TypeForm


class OmitNoneModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")
    kept_when_none: ClassVar[frozenset[str]] = frozenset()

    @model_serializer(mode="wrap")
    def _omit_none(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        serialized = cast("object", handler(self))
        assert isinstance(serialized, dict)
        return {
            key: value
            for key, value in cast("dict[str, object]", serialized).items()
            if value is not None or key in self.kept_when_none
        }


class WebLinkedRecord(OmitNoneModel):
    """A record that also carries a URL pointing away from With Intelligence, such as the firm's
    website, a LinkedIn profile, or an attachment.

    The chat cites a record by its first link field, and with none present it takes any URL on
    the record. `web_url` is sent even when null so that a website or attachment is never cited
    as the record itself.
    """

    kept_when_none: ClassVar[frozenset[str]] = frozenset({"web_url"})

    web_url: str | None = Field(
        default=None,
        description=(
            "This record's page in the With Intelligence web app. Null: With Intelligence "
            "publishes no web app links. Other URLs on the record lead elsewhere."
        ),
    )


def published_output_schema(annotation: object) -> dict[str, object]:
    raw = cast(
        "object", TypeAdapter(cast("TypeForm[object]", annotation)).json_schema(mode="validation")
    )
    assert isinstance(raw, dict)
    schema = {str(key): value for key, value in cast("dict[object, object]", raw).items()}
    if schema.get("type") == "object" or "properties" in schema:
        return schema
    return {"type": "object", **schema}
