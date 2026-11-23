from base64 import urlsafe_b64decode
from base64 import urlsafe_b64encode
from binascii import Error as Base64Error
from collections.abc import Iterable, Mapping, Sequence
import hashlib
from typing import Annotated, ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

# A letter for the kind of entity and 32 hex digits. Checked on every query, the ones a cursor
# carries included, so a malformed pid fails before it spends a request of the Polixis quota.
PID_PATTERN = r"^[POUpou][0-9a-fA-F]{32}$"

QueryPid = Annotated[str, Field(pattern=PID_PATTERN)]


def encode_cursor(query: PageQuery) -> str:
    """An opaque cursor that carries the whole query of the next page, so a caller passes it
    alone. It names the query's type, since two tools' queries can have the same fields.
    """
    payload = f"{type(query).__name__}:{query.model_dump_json()}"
    return urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor[Q: PageQuery](
    cursor: str, query_type: type[Q], *, fixed: Mapping[str, object]
) -> Q:
    """`fixed` holds the fields the decoding tool sets itself, which the cursor's query must
    match, so a cursor of another tool with the same query type fails too.
    """
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        kind, _, encoded = urlsafe_b64decode(padded.encode()).decode().partition(":")
        if kind != query_type.__name__:
            raise ValueError(f"A cursor of {kind}, not {query_type.__name__}")
        query = query_type.model_validate_json(encoded)
        if any(getattr(query, name) != value for name, value in fixed.items()):
            raise ValueError(f"A cursor of another tool's {kind}")
        return query
    except (Base64Error, ValueError) as error:
        raise InvalidCursorError(
            "The cursor is not one this tool returned. Call the tool again without it."
        ) from error


# The rows of one page stop before passing this many tokens, so a page plus its totals stays
# under the 10,000 tokens past which Claude Code warns about a tool result, and well under the
# 25,000 at which it cuts one off by default.
PAGE_TOKENS = 8_000


def page_of[T: BaseModel](
    items: Sequence[T], *, offset: int, size: int | None
) -> tuple[list[T], int | None]:
    """The items of one page, and the offset of the next one or None after the last. A page
    takes items until the next would pass `PAGE_TOKENS`, at least one, and at most `size`.
    """
    page: list[T] = []
    spent = 0
    for item in items[offset : offset + size if size is not None else None]:
        cost = estimated_tokens(item)
        if page and spent + cost > PAGE_TOKENS:
            break
        page.append(item)
        spent += cost
    end = offset + len(page)
    return page, end if end < len(items) else None


def text_page(text: str, *, offset: int) -> tuple[str, int | None]:
    """The part of `text` from `offset` that fits in `PAGE_TOKENS`, cut on a character, and
    the offset of the next part or None after the last.
    """
    part = text[offset:].encode()[: PAGE_TOKENS * 4].decode(errors="ignore")
    end = offset + len(part)
    return part, end if end < len(text) else None


def estimated_tokens(value: BaseModel) -> int:
    """About 4 bytes of JSON a token; text in a non-Latin script, at 2 bytes a character or
    more, comes out close too.
    """
    return len(value.model_dump_json().encode()) // 4


def snapshot_for(query: PageQuery, rows: Iterable[BaseModel | str]) -> str:
    """A digest of `rows`, the whole ranked result a cursor pages through, to put in the next
    cursor. A cursor issued over other rows, as when the cached answer expired between two pages
    and Polixis answered differently, would skip or repeat rows at its offset, so it fails.
    """
    digest = hashlib.sha256()
    for row in rows:
        digest.update((row if isinstance(row, str) else row.model_dump_json()).encode())
        digest.update(b"\0")
    snapshot = digest.hexdigest()[:16]
    if query.snapshot is not None and query.snapshot != snapshot:
        raise ResultChangedError(
            "The result changed since the previous page, so this cursor would skip or repeat "
            "rows. Call the tool again without it."
        )
    return snapshot


class PageQuery(BaseModel):
    """What a paged tool needs to fetch one page. A cursor of another tool fails to decode."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    # Set in a cursor only: the digest of the rows its offset counts into.
    snapshot: str | None = None


class InvalidCursorError(Exception):
    """A cursor that no paged tool of this MCP returned, or one for another tool."""


class ResultChangedError(Exception):
    """A cursor's rows are not the ones the result has now; paging has to start again."""
