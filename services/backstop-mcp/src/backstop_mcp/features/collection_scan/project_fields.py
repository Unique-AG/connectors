"""Build a sparse response row: only the fields the caller asked for.

Intersect the response model's fields with the caller's selection and read the rest off the
DTO. A field whose response shape is not its DTO shape is passed in `overrides`, computed
only when that field is selected.
"""

from collections.abc import Container, Mapping
from typing import cast

from pydantic import BaseModel

__all__ = ["project_fields"]

_NO_OVERRIDES: Mapping[str, object] = {}


def project_fields[ResponseT: BaseModel](
    dto: BaseModel,
    *,
    fields: Container[str],
    into: type[ResponseT],
    overrides: Mapping[str, object] = _NO_OVERRIDES,
) -> ResponseT:
    """`into`, populated from `dto` for the fields in `fields` and left at default for the rest.

    Driven by `into.model_fields` rather than by `fields`, so a selection naming something the
    response does not publish is ignored instead of failing validation.
    """
    values = cast("dict[str, object]", dto.model_dump())
    payload = {
        name: overrides[name] if name in overrides else values[name]
        for name in into.model_fields
        if name in fields and (name in overrides or name in values)
    }
    return into.model_validate(payload)
