from collections.abc import Sequence
from typing import Annotated, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

# PEP 695 generic syntax (not typing.Generic/TypeVar) — pydantic 2.13 resolves
# `BackstopApiResource[SomeModel]` to a concrete model at runtime either way, but this form
# is what basedpyright's strict mode type-checks cleanly for a generic pydantic BaseModel.

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]

_CleanStr: TypeAdapter[str] = TypeAdapter(_NonEmptyStr)


def _clean_str(value: object) -> str | None:
    try:
        return _CleanStr.validate_python(value)
    except ValidationError:
        return None


class BackstopRelationshipRef(BaseModel):
    """The `{type, id}` linkage object inside a JSON:API relationship."""

    type: str | None = None
    id: str | None = None


class BackstopRelationship(BaseModel):
    data: BackstopRelationshipRef | list[BackstopRelationshipRef] | None = None

    def ids(self) -> tuple[str, ...]:
        """Every non-empty related id, whether the relationship is to-one or to-many."""
        if self.data is None:
            return ()
        refs = self.data if isinstance(self.data, list) else [self.data]
        return tuple(ref.id for ref in refs if ref.id)


class BackstopApiResource[AttrT](BaseModel):
    # `min_length=1` (checked post-strip) rejects a present-but-blank id as a schema
    # validation failure — same failure mode as a missing id, since neither is a usable
    # resource identifier. `type` is only stripped: a blank type is a caller-side display
    # concern (see party_resolver.search), not a structural defect worth failing on here.
    id: _NonEmptyStr
    type: _StrippedStr
    attributes: AttrT
    # Present whenever a resource links to others. Needed to follow an `?include=` target to
    # its side-loaded resource: the primary resource carries only the `{type, id}` reference,
    # and the resource itself arrives in the document's top-level `included` array.
    relationships: dict[str, BackstopRelationship] = Field(default_factory=dict)

    def related_ids(self, name: str) -> tuple[str, ...]:
        relationship = self.relationships.get(name)
        return relationship.ids() if relationship is not None else ()


class _JsonApiDocument(BaseModel):
    # JSON:API puts `?include=`d resources here — same field pagination keeps on each page.
    # Without it, a by-id GET with `?include=entityRelationships` would silently drop the
    # side-loaded resources the caller paid a request to fetch.
    included: list[dict[str, object]] = Field(default_factory=list)


class BackstopApiResourceDocument[AttrT](_JsonApiDocument):
    """A by-id JSON:API document: `data` is exactly one resource.

    Null primary data is a schema failure (Backstop returns 404 for missing by-id records,
    which the client raises before deserialization).
    """

    data: BackstopApiResource[AttrT]


class BackstopApiCollectionDocument[AttrT](_JsonApiDocument):
    """A list JSON:API document: `data` is always an array of resources."""

    data: list[BackstopApiResource[AttrT]]


class ResourceRef(BaseModel):
    """Backstop's inline reference to another record, embedded in an attribute value.

    Backstop's *second* reference format. JSON:API linkage under `relationships` is `{type, id}`
    and is resolved by `follow_included`; some attributes instead carry an inline
    `{resourceType, resourceId, resourceLink, restricted}` object
    (`opportunity-stage-history.attributes.stage`, the values inside `regularCustomFieldValues`).
    Modelling it here means the second format is handled explicitly wherever it turns up rather
    than read as an opaque dict.

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


def follow_included[AttrT](
    included: Sequence[dict[str, object]],
    resource: BackstopApiResource[AttrT],
    relationship_name: str,
) -> list[dict[str, object]]:
    """The entries of `included` linked from `resource` via `relationship_name`.

    Takes the side-loaded resources rather than the document they arrived in, so a paginated walk
    can hand over its accumulated `included` without building an intermediate document.

    Matches entries by JSON:API identity `(type, id)` — ids alone are not unique across resource
    types in the same `included` array (e.g. entity-relationships and entity-relationship-types
    can share numeric ids). Order follows the relationship linkage, not the `included` order.
    """
    relationship = resource.relationships.get(relationship_name)
    if relationship is None or relationship.data is None:
        return []
    refs = relationship.data if isinstance(relationship.data, list) else [relationship.data]
    wanted = tuple(
        (_clean_str(ref.type), related_id)
        for ref in refs
        if (related_id := _clean_str(ref.id)) is not None
    )
    if not wanted:
        return []
    by_identity = {
        (_clean_str(item.get("type")), item_id): item
        for item in included
        if (item_id := _clean_str(item.get("id"))) is not None
    }
    return [by_identity[key] for key in wanted if key in by_identity]


def included_by_type(
    included: Sequence[dict[str, object]], resource_type: str
) -> list[dict[str, object]]:
    """The entries of `included` carrying one JSON:API `type`.

    Selected by `type` rather than followed from a linkage, because a nested include
    (`entityRelationships.entityRelationshipType`) puts the second hop's resources in the same
    `included` array with nothing on the primary resource pointing at them.
    """
    return [item for item in included if _clean_str(item.get("type")) == resource_type]
