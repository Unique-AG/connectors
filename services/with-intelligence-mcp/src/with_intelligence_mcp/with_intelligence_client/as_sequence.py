"""Tolerating the vendor's inconsistent array encoding.

The spec's array/object distinction does not hold in either direction: `consultants` is declared
an array and arrives as `{"0": {...}, "1": {...}}`, while `asset_allocation_breakdown` is
declared an object and arrives as a list. So every list field accepts both rather than only the
one that happened to be guessed right.
"""

from typing import cast

from pydantic import BeforeValidator


def as_sequence(value: object) -> object:
    if not isinstance(value, dict):
        return value
    entries = cast(dict[str, object], value)
    try:
        return [entries[key] for key in sorted(entries, key=int)]
    except ValueError:
        return list(entries.values())


SEQUENCE = BeforeValidator(as_sequence)
