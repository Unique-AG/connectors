from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel


class _Named(Protocol):
    name: str | None


def names(values: Sequence[_Named] | None) -> list[str]:
    if values is None:
        return []
    return [value.name for value in values if value.name]


def when_present[T](attributes: BaseModel, field: str, value: T) -> T | None:
    return value if field in attributes.model_fields_set else None


def when_either[T](attributes: BaseModel, fields: Sequence[str], value: T) -> T | None:
    if any(field in attributes.model_fields_set for field in fields):
        return value
    return None
