"""Narrowing helpers for values whose type is only known at runtime.

For the corners of Backstop's API that the swagger declares as free-form objects (`lovSet`,
`selectOptions`) and for anything else read out of an untyped `dict[str, object]`. Each returns
an empty/None result rather than raising, so a caller can try several shapes in turn.

Not for narrowing a *typed* pydantic union — `BackstopApiResource | list[...] | None` is checked
with a plain `isinstance` at the point of use, since the type already tells you the options.
"""

from typing import cast


def as_object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, object]", value)


def as_object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast("list[object]", value)
