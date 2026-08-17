"""The shape the includes package is built from.

`Include` is the Backstop half of one include, attached to the field it fills in on a segment's
includes model. The other half — whether the include is to-one and what model it projects onto —
is the field's own annotation, so it is never restated here.
"""

from dataclasses import dataclass


# A dataclass, not a `BaseModel`, and it must stay one: a pydantic model inside an `Annotated[...]`
# chain replaces the field's schema with `{"$ref": "#/$defs/Include"}`, so the real type and every
# nested description vanish from the published schema. A dataclass is inert metadata.
# `tests/features/includes/test_responses.py` fails if this is changed back.
@dataclass(frozen=True, slots=True, kw_only=True)
class Include:
    """Backstop's side of one include: what to ask for, and what type comes back.

    `relationship` is Backstop's own name, which is what goes in `?include=`; the field this sits
    on is the name *we* expose, and the two deliberately differ where Backstop's would mislead
    (`contactEmails` → `email_addresses`).

    `resource_type` is the JSON:API `type` the side-loaded resources arrive under, so a resource
    of some other type cannot be read as this one.
    """

    relationship: str
    resource_type: str
