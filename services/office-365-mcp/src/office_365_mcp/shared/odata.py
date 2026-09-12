"""OData string-literal quoting: a value inside a `$filter` that Graph reads as text, never syntax.

The sibling of `shared/kql.py`, for the other query language this connector writes. Both exist for
the same reason: the escape is shared rather than copied into each tool, because a copy can drift
out of sync with this one, and a drifted escape does not look wrong — it composes a query that
still parses and answers a different question.

Three tools put a caller's or a handle's value inside an OData string literal, and each one of
them had its own spelling of this before it lived here. That is one spelling per place a value can
end the literal early.

Nothing here decides which property a value is compared on, or how. That is each tool's own
knowledge, and the properties Graph will accept differ per collection.
"""


def odata_literal(value: str) -> str:
    """`value` as the inside of a single-quoted OData string literal.

    Doubling is how OData escapes a single quote within a string literal, and doubling keeps the
    count even, so the literal cannot be closed from inside. An unescaped quote ends the literal
    and leaves the rest of the value as predicate syntax — which is a correctness bug on an
    address like `o'brien@example.com` before it is anything else, because Graph answers the
    malformed filter rather than the intended one.

    This returns the inside, not the literal: the caller writes the surrounding quotes. Wrapping
    them here would read as "already quoted" at the call site and invite a second pair.
    """
    return value.replace("'", "''")
