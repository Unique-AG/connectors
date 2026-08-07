"""Narrowing helpers for values whose type is only known at runtime.

For the corners of Backstop's API that the swagger declares as free-form objects (`lovSet`,
`selectOptions`) and for anything else read out of an untyped `dict[str, object]`. Each returns
an empty/None result rather than raising, so a caller can try several shapes in turn.

Not for narrowing a *typed* pydantic union — `BackstopApiResource | list[...] | None` is checked
with a plain `isinstance` at the point of use, since the type already tells you the options.
Typed string fields should use `Annotated[str, StringConstraints(...)]` on the model itself.
"""

from typing import Annotated, cast

from pydantic import StringConstraints, TypeAdapter, ValidationError

_CleanStr: TypeAdapter[str] = TypeAdapter(
    Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
)


def as_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, object]", value)


def as_object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast("list[object]", value)


def as_clean_str(value: object) -> str | None:
    """A stripped non-empty string, or None for anything else (including blank strings)."""
    try:
        return _CleanStr.validate_python(value)
    except ValidationError:
        return None
