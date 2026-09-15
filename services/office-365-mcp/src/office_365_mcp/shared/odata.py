"""OData string-literal quoting: a value inside a `$filter` that Graph reads as text, never syntax.

The sibling of `shared/kql.py`. Shared rather than copied per tool, because a drifted escape does
not look wrong — it composes a query that still parses and answers a different question.
"""


def odata_literal(value: str) -> str:
    """`value` as the inside of a single-quoted OData string literal; the caller writes the quotes.

    Doubling is OData's escape. An unescaped quote ends the literal and leaves the rest of the
    value as predicate syntax, so Graph answers a malformed filter rather than the intended one —
    on an address like `o'brien@example.com` before it is anything else.
    """
    return value.replace("'", "''")
