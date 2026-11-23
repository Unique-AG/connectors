from typing import cast, ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_serializer
from pydantic import SerializerFunctionWrapHandler

_EXACT_FLOAT_LIMIT = 2**53


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


class Reply(BaseModel):
    """What every tool answers with. Kyckr's own top-level fields, such as `cost` and `links`,
    come along as they are, empty fields are left out, and a whole number stays a whole number.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")

    success: bool = Field(description="False when the call to Kyckr failed.")
    statusCode: int | None = Field(  # noqa: N815 (Kyckr's wire name)
        None,
        description=(
            "The HTTP status Kyckr answered a failed call with. 400 is a bad parameter, 401 a "
            "problem with the server's Kyckr credential, 403 a feature the account lacks, 404 an "
            "unknown id, 405 an enhanced profile not available for that jurisdiction, 410 an "
            "order that is gone for good (do not retry) and 429 a rate limit."
        ),
    )
    message: str | None = Field(None, description="Why the call failed.")
    correlationId: str | None = Field(  # noqa: N815 (Kyckr's wire name)
        None, description="Kyckr's id for the request, to quote to its support."
    )
    details: str | None = Field(None, description="Kyckr's status details for the request.")
    data: object | None = Field(None, description="What Kyckr returned, as Kyckr names it.")

    @model_serializer(mode="wrap")
    def _omit_empty_fields(self, handler: SerializerFunctionWrapHandler):  # noqa: ANN202
        # No return annotation: one would replace the output schema FastMCP publishes.
        return _tidy(cast(object, handler(self)))  # noqa: TC006


def answer[R: Reply](reply: type[R], response: BaseModel) -> R:
    """A successful reply of the given type, made from what Kyckr returned."""
    return reply.model_validate({**response.model_dump(by_alias=True), "success": True})


class CompanyDocumentsReply(Reply):
    continuationKey: str | None = Field(  # noqa: N815 (Kyckr's wire name)
        None,
        description=(
            "Pass it back as `continuation_key` to fetch the next page. Absent on the last page."
        ),
    )
