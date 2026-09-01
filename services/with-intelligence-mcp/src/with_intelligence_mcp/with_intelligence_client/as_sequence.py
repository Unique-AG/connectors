"""Tolerating the vendor's inconsistent array encoding.

The spec's array/object distinction does not hold in either direction, and has now been wrong
five times against real responses: `consultants` is declared an array and arrives as
`{"0": {...}, "1": {...}}`; `asset_allocation_breakdown` is declared an object and arrives as a
list; `secondary_strategies`, `ranges_usd` and `person_roles[].specialisms` are each declared a
single object and arrive as a list of them.

So the coercions here are applied to every nested field rather than to the ones already caught:
`SEQUENCE` accepts either encoding for a field we model as a list, and `SINGLE` accepts a list
for a field we model as one object. Whichever way the next surprise goes, it parses.
"""

from typing import cast

from pydantic import BeforeValidator


def as_sequence(value: object) -> object:
    """Normalise to a list: a list stays, an index-keyed object flattens, one object wraps.

    The three cases are told apart by their keys, not guessed. An index-keyed object has only
    digit keys (`{"0": ..., "1": ...}`); anything else is a single record that belongs in a
    one-element list. Reading `.values()` off a single record would yield its field *values* as
    the list, which is how `{"id": 4, "name": "Real Assets"}` became `[4, "Real Assets"]`.
    """
    if not isinstance(value, dict):
        return value
    entries = cast(dict[str, object], value)
    if not entries:
        return []
    if all(key.isdigit() for key in entries):
        return [entries[key] for key in sorted(entries, key=int)]
    return [entries]


def as_single(value: object) -> object:
    """Normalise to one object: a list collapses to its first element, empty to `None`.

    For a field the spec declares as a single object. Lossy only in the case the spec says
    cannot happen, and the alternative there is a failed tool call.
    """
    if not isinstance(value, list):
        return value
    entries = cast(list[object], value)
    return entries[0] if entries else None


SEQUENCE = BeforeValidator(as_sequence)
SINGLE = BeforeValidator(as_single)
