"""OData wire helpers: quote a `$filter` value as text, and spell a Graph enum as its wire value.

The sibling of `shared/kql.py`. Shared rather than copied per tool, because a drifted escape does
not look wrong — it composes a query that still parses and answers a different question.
"""

from typing import overload


def odata_literal(value: str) -> str:
    """`value` as the inside of a single-quoted OData string literal; the caller writes the quotes.

    Doubling is OData's escape. An unescaped quote ends the literal and leaves the rest of the
    value as predicate syntax, so Graph answers a malformed filter rather than the intended one —
    on an address like `o'brien@example.com` before it is anything else.
    """
    return value.replace("'", "''")


@overload
def spelled(value: str) -> str: ...
@overload
def spelled(value: None) -> None: ...
@overload
def spelled(value: str | None) -> str | None: ...
def spelled(value: str | None) -> str | None:
    return None if value is None else str.__str__(value)
