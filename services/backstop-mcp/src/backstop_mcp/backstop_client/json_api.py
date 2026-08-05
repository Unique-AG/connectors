from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from backstop_mcp.backstop_client.errors import BackstopUnexpectedCollectionError
from backstop_mcp.coerce import as_clean_str

# PEP 695 generic syntax (not typing.Generic/TypeVar) — pydantic 2.13 resolves
# `BackstopApiResource[SomeModel]` to a concrete model at runtime either way, but this form
# is what basedpyright's strict mode type-checks cleanly for a generic pydantic BaseModel.


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


class BackstopApiDocument[AttrT](BaseModel):
    data: BackstopApiResource[AttrT] | list[BackstopApiResource[AttrT]] | None
    # JSON:API puts `?include=`d resources here — same field pagination keeps on each page.
    # Without it, a by-id GET with `?include=entityRelationships` would silently drop the
    # side-loaded resources the caller paid a request to fetch.
    included: list[dict[str, object]] = Field(default_factory=list)


def single_resource[AttrT](
    document: BackstopApiDocument[AttrT], *, path: str
) -> BackstopApiResource[AttrT] | None:
    """The one resource a by-id fetch returned, or None if the document describes none.

    Raises `BackstopUnexpectedCollectionError` for a collection: `data` is a union because one
    document shape covers both list and by-id reads, but a caller that asked for `/{entity}/{id}`
    has no use for a list and every such caller wants the same typed failure.
    """
    if isinstance(document.data, list):
        raise BackstopUnexpectedCollectionError(path)
    return document.data


def included_for_relationship[AttrT](
    document: BackstopApiDocument[AttrT],
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
        (as_clean_str(ref.type), related_id)
        for ref in refs
        if (related_id := as_clean_str(ref.id)) is not None
    )
    if not wanted:
        return []
    by_identity = {
        (as_clean_str(item.get("type")), item_id): item
        for item in document.included
        if (item_id := as_clean_str(item.get("id"))) is not None
    }
    return [by_identity[key] for key in wanted if key in by_identity]


def included_of_type[AttrT](
    document: BackstopApiDocument[AttrT], resource_type: str
) -> list[dict[str, object]]:
    """Every side-loaded resource carrying one JSON:API `type`.

    Selected by `type` rather than followed from a linkage, because a nested include
    (`entityRelationships.entityRelationshipType`) puts the second hop's resources in the same
    `included` array with nothing on the primary resource pointing at them.
    """
    return [item for item in document.included if as_clean_str(item.get("type")) == resource_type]
