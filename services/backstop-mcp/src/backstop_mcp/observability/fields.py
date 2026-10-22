"""Log `extra` fields as OpenTelemetry attribute values."""

from collections.abc import Iterable, Mapping
from typing import cast

from opentelemetry.util.types import AttributeValue


def span_attributes(fields: Mapping[str, object]) -> dict[str, AttributeValue]:
    """`None` is dropped; scalars pass through; collections become string tuples; anything else,
    `IdentifiableValue` included, goes through `str()` — which is what conceals it.
    """
    return {key: _attribute_value(value) for key, value in fields.items() if value is not None}


def _attribute_value(value: object) -> AttributeValue:
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(str(item) for item in cast("Iterable[object]", value))
    return str(value)
