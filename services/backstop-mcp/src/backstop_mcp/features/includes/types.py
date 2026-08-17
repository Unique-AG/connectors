"""The two shapes the includes package is built from.

`Include` is the Backstop half of one include, attached to the field it fills in on a segment's
includes model. The other half — whether the include is to-one and what model it projects onto —
is the field's own annotation, so it is never restated here.

`ResourceRef` is Backstop's *second* reference format. JSON:API linkage under `relationships`
is `{type, id}` and is resolved by `follow_included`; some attributes instead carry an inline
`{resourceType, resourceId, resourceLink}` object (`opportunity-stage-history.attributes.stage`,
the values inside `regularCustomFieldValues`). Modelling it here means the second format is
handled explicitly wherever it turns up rather than read as an opaque dict.
"""

from dataclasses import dataclass
from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


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


class ResourceRef(BaseModel):
    """Backstop's inline reference to another record, embedded in an attribute value.

    `resource_id` is required because a reference nobody can resolve is not a reference; the
    type and the link are optional, since the id plus the attribute it sits on is enough to look
    a record up.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    resource_id: _NonEmptyStr = Field(
        alias="resourceId", description="Backstop id of the referenced record."
    )
    resource_type: _StrippedStr | None = Field(
        default=None,
        alias="resourceType",
        description="JSON:API type of the referenced record, e.g. `opportunity-stages`.",
    )
    resource_link: _StrippedStr | None = Field(
        default=None,
        alias="resourceLink",
        description="Backstop API URL of the referenced record.",
    )
