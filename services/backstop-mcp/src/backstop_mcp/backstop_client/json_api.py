from pydantic import BaseModel

# PEP 695 generic syntax (not typing.Generic/TypeVar) — pydantic 2.13 resolves
# `JsonApiResource[SomeModel]` to a concrete model at runtime either way, but this form
# is what basedpyright's strict mode type-checks cleanly for a generic pydantic BaseModel.


class JsonApiResource[AttrT](BaseModel):
    id: str
    type: str
    attributes: AttrT


class JsonApiDocument[AttrT](BaseModel):
    data: JsonApiResource[AttrT] | list[JsonApiResource[AttrT]] | None
