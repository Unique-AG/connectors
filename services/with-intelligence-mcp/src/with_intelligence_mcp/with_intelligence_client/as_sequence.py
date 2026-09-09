"""Normalize inconsistent WI object and list payloads."""

from typing import cast

from pydantic import BeforeValidator


def as_sequence(value: object) -> object:
    """Normalize mappings to list representations."""
    if not isinstance(value, dict):
        return value
    entries = cast(dict[str, object], value)
    if not entries:
        return []
    if all(key.isdigit() for key in entries):
        return [entries[key] for key in sorted(entries, key=int)]
    return [entries]


def as_single(value: object) -> object:
    """Unwrap the first list item while preserving non-list values."""
    if not isinstance(value, list):
        return value
    entries = cast(list[object], value)
    return entries[0] if entries else None


SEQUENCE = BeforeValidator(as_sequence)
SINGLE = BeforeValidator(as_single)
