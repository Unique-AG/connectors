"""Coerce unparseable scalars to None so one junk field cannot fail a record."""

from typing import Annotated

from pydantic import BeforeValidator, TypeAdapter, ValidationError

_bool_adapter: TypeAdapter[bool] = TypeAdapter(bool)
_int_adapter: TypeAdapter[int] = TypeAdapter(int)
_float_adapter: TypeAdapter[float] = TypeAdapter(float)


def _coerce[T](adapter: TypeAdapter[T], value: object) -> T | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return adapter.validate_python(value)
    except ValidationError:
        return None


def _parse_lenient_bool(value: object) -> bool | None:
    return _coerce(_bool_adapter, value)


def _parse_lenient_int(value: object) -> int | None:
    return _coerce(_int_adapter, value)


def _parse_lenient_float(value: object) -> float | None:
    return _coerce(_float_adapter, value)


def _parse_lenient_str(value: object) -> str | None:
    """A stripped string, or None for a blank one and for anything that is not a string.

    Deliberately does not stringify numbers or bools: these are display fields, and a `name` that
    arrived as `42` is a defect worth reporting as absent rather than as the text "42".
    """
    if not isinstance(value, str):
        return None
    return value.strip() or None


LenientBool = Annotated[bool | None, BeforeValidator(_parse_lenient_bool)]
LenientInt = Annotated[int | None, BeforeValidator(_parse_lenient_int)]
LenientFloat = Annotated[float | None, BeforeValidator(_parse_lenient_float)]
LenientStr = Annotated[str | None, BeforeValidator(_parse_lenient_str)]
