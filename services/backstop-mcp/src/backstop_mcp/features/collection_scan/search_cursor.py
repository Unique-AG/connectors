"""The opaque cursor a paged search hands back, and the check that it belongs to this search.

A cursor is the position of the next unread record in each server-ordered collection the
search reads, plus a fingerprint of every other argument. Resuming with different arguments
would read the right offset of the wrong result set, so a mismatched cursor is rejected
instead of quietly returning rows from a different query.
"""

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from typing import ClassVar, Literal, Self

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_core import to_jsonable_python

__all__ = ["InvalidCursorError", "SearchCursor", "search_fingerprint"]

_MISMATCH = (
    "This cursor belongs to a different search. Pass it back to the same tool with every other "
    "argument unchanged, or omit `cursor` to start a new search."
)
_MALFORMED = (
    "This cursor is not one this server issued. `cursor` takes the exact `continuation.cursor` "
    "string from the previous page, copied unchanged; it is not a page number or an offset. Omit "
    "`cursor` to start the search over."
)


class InvalidCursorError(ToolError):
    """A cursor the model passed back that is malformed or belongs to another search."""


def search_fingerprint(tool: str, arguments: Mapping[str, object]) -> str:
    """A short, stable digest of a search's arguments, cursor excluded."""
    canonical = json.dumps(
        {"tool": tool, "arguments": to_jsonable_python(arguments)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class SearchCursor(BaseModel):
    """Where the next page starts: one offset per collection the search reads."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    v: Literal[1] = 1
    offsets: tuple[int, ...] = Field(min_length=1)
    fingerprint: str

    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str, *, fingerprint: str, collections: int) -> Self:
        """Parse a cursor the model passed back; reject one from another search.

        The cursor is model input, so a bad one is an `InvalidCursorError` (a `ToolError`) the
        model can act on rather than an internal assertion.
        """
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            cursor = cls.model_validate_json(raw)
        except (binascii.Error, ValueError, ValidationError) as exc:
            raise InvalidCursorError(_MALFORMED) from exc
        if cursor.fingerprint != fingerprint:
            raise InvalidCursorError(_MISMATCH)
        if len(cursor.offsets) != collections or any(offset < 0 for offset in cursor.offsets):
            raise InvalidCursorError(_MALFORMED)
        return cursor
