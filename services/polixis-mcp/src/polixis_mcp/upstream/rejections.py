from typing import Protocol, runtime_checkable

from mcp_openapi.upstream import UpstreamError
from pydantic import BaseModel
from pydantic import JsonValue
from pydantic import ValidationError


def reject_error_body(response: object) -> None:
    """The client's response check: Polixis answers some failures, such as an id it does not
    know, with a 200 whose body is `error` and `code` in place of the response.
    """
    if isinstance(response, _MayBeRejected) and response.error is not None:
        raise PolixisRejectedError(
            f"Polixis rejected the request ({response.code or 'no code'}): {response.error}"
        )


def is_rejection_body(body: bytes) -> bool:
    """Whether a 200's body is such a rejection, read from the JSON itself, so a response
    model without `error` does not hide it.
    """
    try:
        return _RejectionBody.model_validate_json(body).error is not None
    except ValidationError:
        return False


class PolixisRejectedError(UpstreamError):
    """Polixis answered with a 200 whose body is an error, such as for an id it does not know."""


@runtime_checkable
class _MayBeRejected(Protocol):
    @property
    def error(self) -> str | None: ...

    @property
    def code(self) -> str | None: ...


class _RejectionBody(BaseModel):
    error: JsonValue = None
