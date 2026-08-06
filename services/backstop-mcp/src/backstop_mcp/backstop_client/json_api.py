from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, TypeAdapter, ValidationError

# PEP 695 generic syntax (not typing.Generic/TypeVar) — pydantic 2.13 resolves
# `BackstopApiResource[SomeModel]` to a concrete model at runtime either way, but this form
# is what basedpyright's strict mode type-checks cleanly for a generic pydantic BaseModel.

_CleanStr = TypeAdapter(Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)])


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
    id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    type: Annotated[str, StringConstraints(strip_whitespace=True)]
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


def follow_included[AttrT](
    document: _JsonApiDocument,
    resource: BackstopApiResource[AttrT],
    relationship_name: str,
) -> list[dict[str, object]]:
    """Side-loaded resources linked from `resource` via `relationship_name`.

    Matches `included` entries by JSON:API identity `(type, id)` — ids alone are not unique
    across resource types in the same `included` array (e.g. entity-relationships and
    entity-relationship-types can share numeric ids). Order follows the relationship
    linkage, not the `included` array order.
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
        for item in document.included
        if (item_id := _clean_str(item.get("id"))) is not None
    }
    return [by_identity[key] for key in wanted if key in by_identity]


def included_by_type(document: _JsonApiDocument, resource_type: str) -> list[dict[str, object]]:
    """Every side-loaded resource carrying one JSON:API `type`.

    Selected by `type` rather than followed from a linkage, because a nested include
    (`entityRelationships.entityRelationshipType`) puts the second hop's resources in the same
    `included` array with nothing on the primary resource pointing at them.
    """
    return [item for item in document.included if _clean_str(item.get("type")) == resource_type]
