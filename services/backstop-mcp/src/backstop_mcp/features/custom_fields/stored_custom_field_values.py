"""Read a record's `regularCustomFieldValues` as text, without the definition catalog.

Search and listing walks carry the stored values on every record. These helpers turn them into
`StoredCustomFieldValueResponse` rows and test them against the `custom_fields` predicates, so
the people, organization, opportunity, and account walks share one reading of a stored value.
"""

from collections.abc import Iterator, Sequence
from typing import NamedTuple, cast

from backstop_mcp.features.custom_fields.api_responses import CustomFieldValueAttributes
from backstop_mcp.features.custom_fields.responses import StoredCustomFieldValueResponse

__all__ = [
    "CustomFieldMatch",
    "display_text",
    "normalize_matches",
    "satisfies_every",
    "stored_custom_field_values",
]


class CustomFieldMatch(NamedTuple):
    """One custom-field predicate: definition id, then the stored values that satisfy it (OR)."""

    definition_id: str
    values: tuple[str, ...]


def _scalar_text(stored: object) -> str | None:
    if isinstance(stored, bool):
        return "true" if stored else "false"
    if isinstance(stored, str):
        return stored.strip() or None
    if isinstance(stored, int | float):
        return str(stored)
    return None


def _scalar_texts(stored: object) -> Iterator[str]:
    if isinstance(stored, list):
        for item in cast("list[object]", stored):
            yield from _scalar_texts(item)
        return
    text = _scalar_text(stored)
    if text is not None:
        yield text


def display_text(stored: object) -> str | None:
    """The stored value as text, a multi-select joined with '; ', or None when it is unset."""
    return "; ".join(_scalar_texts(stored)) or None


def stored_custom_field_values(
    values: Sequence[CustomFieldValueAttributes],
) -> tuple[StoredCustomFieldValueResponse, ...]:
    """Every value that is set, in wire order. A record's unset fields are absent."""
    return tuple(
        StoredCustomFieldValueResponse(
            definition_id=value.definition_id, name=value.name, value=text
        )
        for value in values
        if value.definition_id and (text := display_text(value.value)) is not None
    )


def normalize_matches(matches: Sequence[CustomFieldMatch]) -> tuple[CustomFieldMatch, ...]:
    """Strip ids and values and drop a predicate left with no id or no value."""
    normalized = (
        CustomFieldMatch(
            definition_id=match.definition_id.strip(),
            values=tuple(value.strip() for value in match.values if value.strip()),
        )
        for match in matches
    )
    return tuple(match for match in normalized if match.definition_id and match.values)


def satisfies_every(
    values: Sequence[CustomFieldValueAttributes], matches: Sequence[CustomFieldMatch]
) -> bool:
    """True when every predicate has a stored value equal, case-insensitively, to one of its values.

    A list value matches when any element does. A missing value never matches. No predicates
    match every record.
    """
    for match in matches:
        needles = frozenset(value.casefold() for value in match.values)
        if not any(
            text.casefold() in needles
            for value in values
            if value.definition_id == match.definition_id
            for text in _scalar_texts(value.value)
        ):
            return False
    return True
