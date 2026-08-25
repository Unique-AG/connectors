"""Build a sparse response row: only the fields the caller asked for, once.

Both collection-scanning tools publish "only the fields you named" rows, and both had written
the same projection out by hand — nineteen `if "x" in fields` branches in one, twenty-one inline
`x if "x" in include else None` kwargs in the other. Both are the same operation: intersect the
response model's fields with the caller's selection, read the rest off the DTO.

A field whose response shape is not its DTO shape (plain text out of HTML, say) is passed in
`overrides`, computed by the caller only when that field is selected. Everything else is carried
by name: a nested DTO dumps to a mapping and the nested response model validates it, which is
what both call sites were already doing by hand for their chips.
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
