from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

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
