from typing import Annotated

from pydantic import BaseModel, StringConstraints

# PEP 695 generic syntax (not typing.Generic/TypeVar) — pydantic 2.13 resolves
# `BackstopApiResource[SomeModel]` to a concrete model at runtime either way, but this form
# is what basedpyright's strict mode type-checks cleanly for a generic pydantic BaseModel.


class BackstopApiResource[AttrT](BaseModel):
    # `min_length=1` (checked post-strip) rejects a present-but-blank id as a schema
    # validation failure — same failure mode as a missing id, since neither is a usable
    # resource identifier. `type` is only stripped: a blank type is a caller-side display
    # concern (see party_resolver.search), not a structural defect worth failing on here.
    id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    type: Annotated[str, StringConstraints(strip_whitespace=True)]
    attributes: AttrT


class BackstopApiDocument[AttrT](BaseModel):
    data: BackstopApiResource[AttrT] | list[BackstopApiResource[AttrT]] | None
