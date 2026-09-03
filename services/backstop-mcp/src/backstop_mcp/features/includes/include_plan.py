"""Turn requested include names into a query param, and side-loads into projections.

`include_plan` reads everything it needs off the includes model it is pointed at: each field's
`Include` metadata says which Backstop relationship to ask for, and the field's annotation says
whether one record or a list comes back and what to project it onto. The plan then carries both
halves of one segment's request — the `?include=` value to send and the model to answer in — so
the query cannot be built from one segment while the answer is projected into another, and the
caller keeps the field types instead of an opaque `BaseModel`.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from types import UnionType
from typing import ClassVar, get_args, get_origin, overload

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.fields import FieldInfo

from backstop_mcp.backstop_client import (
    BackstopApiResourceDocument,
    Included,
    IncludedResource,
)
from backstop_mcp.features.includes.responses import (
    ActivityInclude,
    ActivityIncludesResponse,
    OrganizationInclude,
    OrganizationIncludesResponse,
    PersonInclude,
    PersonIncludesResponse,
)
from backstop_mcp.features.includes.types import Include

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PlannedInclude:
    """One requested include, resolved: the field it fills and everything needed to fill it."""

    name: str
    include: Include
    model: type[BaseModel]
    to_one: bool


@dataclass(frozen=True, slots=True)
class IncludePlan[ResponseT: BaseModel]:
    """One segment's include request: the query value to send, and how to read the answer.

    `param` is `""` when nothing was requested, so a caller that composes it with an include of
    its own (`get_person` always side-loads `entityRelationships`) must not emit a leading comma.
    """

    param: str
    into: type[ResponseT]
    planned: tuple[_PlannedInclude, ...]

    def project[AttrT](self, *, document: BackstopApiResourceDocument[AttrT]) -> ResponseT:
        """The document's side-loads for this plan, projected onto `into`.

        Three distinctions survive into the model, where an omitted key becomes a `None` field:

        * A name that was not requested is **absent** — never present as `None`.
        * A requested to-many include is **always present**, `[]` when there is nothing to
          return: "we looked, there are none" rather than "we did not look".
        * A requested to-one include is absent when the relationship points at nothing, and
          equally when its one resource was dropped, since there is no empty single resource to
          return.

        A side-loaded resource that fails to validate, or that arrives under a JSON:API `type`
        other than the one the field's `Include` names, is warned about and dropped on its own, so
        one unreadable location does not cost the caller the other three. A relationship whose
        linkage resolves to nothing at all is warned about too: the usual cause is a caller that
        forgot to put `param` in the request's query string, and an empty answer would otherwise
        read as "there are none".
        """
        projected: dict[str, BaseModel | list[BaseModel]] = {}
        for planned in self.planned:
            models = _include_resources(document=document, planned=planned)
            if not planned.to_one:
                projected[planned.name] = models
            elif models:
                projected[planned.name] = models[0]
        return self.into.model_validate(projected)


# One overload per includes model, so the include names are checked against the model they are
# being projected into. A single generic signature cannot express this: `requested: Sequence[NameT]`
# with `NameT` tied to the model is either illegal (a PEP 695 bound may not reference another
# type parameter) or silently widened — basedpyright solves the mismatched call as
# `Sequence[str]`, or unions the two models, instead of reporting it. Overloads also give the
# call site completion on the valid names.
@overload
def include_plan(
    into: type[OrganizationIncludesResponse], *, requested: Sequence[OrganizationInclude]
) -> IncludePlan[OrganizationIncludesResponse]: ...
@overload
def include_plan(
    into: type[PersonIncludesResponse], *, requested: Sequence[PersonInclude]
) -> IncludePlan[PersonIncludesResponse]: ...
@overload
def include_plan(
    into: type[ActivityIncludesResponse], *, requested: Sequence[ActivityInclude]
) -> IncludePlan[ActivityIncludesResponse]: ...
def include_plan[ResponseT: BaseModel](
    into: type[ResponseT], *, requested: Sequence[str]
) -> IncludePlan[ResponseT]:
    """The plan for `requested` on `into` — what to ask Backstop for, and how to read it back.

    An unrecognised name is an internal invariant, not user input: the overloads above reject one
    at the call site, and the tools type their `include` parameter as the same `Literal`, so
    FastMCP rejects anything else at the MCP boundary. A name that got this far means the model
    and the parameter have drifted apart.
    """
    unknown = [name for name in requested if name not in into.model_fields]
    assert not unknown, f"{into.__name__} declares no field for these include names: {unknown}"
    planned = tuple(
        _plan(into=into, name=name)
        for name in dict.fromkeys(requested)  # deduplicated, in order
    )
    return IncludePlan(
        param=",".join(dict.fromkeys(one.include.relationship for one in planned)),
        into=into,
        planned=planned,
    )


def _plan(*, into: type[BaseModel], name: str) -> _PlannedInclude:
    field = into.model_fields[name]
    metadata: list[object] = field.metadata
    include = next((meta for meta in metadata if isinstance(meta, Include)), None)
    assert include is not None, f"{into.__name__}.{name} carries no Include metadata"
    model, to_one = _target(field=field, where=f"{into.__name__}.{name}")
    return _PlannedInclude(name=name, include=include, model=model, to_one=to_one)


def _target(*, field: FieldInfo, where: str) -> tuple[type[BaseModel], bool]:
    """What a field's annotation promises: the model to project onto, and whether it is to-one.

    `list[X] | None` is to-many onto `X`; `X | None` is to-one onto `X`. The `None` arm is what
    "not requested" is expressed as, so every includes field carries it.
    """
    annotation = field.annotation
    assert get_origin(annotation) is UnionType, f"{where} is not `X | None`: {annotation}"
    arms: tuple[object, ...] = get_args(annotation)
    carried = [arm for arm in arms if arm is not type(None)]
    assert len(carried) == 1, f"{where} is not `X | None`: {annotation}"
    inner = carried[0]
    if get_origin(inner) is list:
        items: tuple[object, ...] = get_args(inner)
        (item,) = items
        assert isinstance(item, type) and issubclass(item, BaseModel), (
            f"{where} is not a list of models: {inner}"
        )
        return item, False
    assert isinstance(inner, type) and issubclass(inner, BaseModel), (
        f"{where} is not a model: {inner}"
    )
    return inner, True


class _IncludeAttributes(BaseModel):
    """Wire attributes of the resource an `Include` names; extras stay so `id` can be folded in."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")


_IncludeResource = IncludedResource[_IncludeAttributes]


def _include_resources[AttrT](
    *, document: BackstopApiResourceDocument[AttrT], planned: _PlannedInclude
) -> list[BaseModel]:
    """Every related resource for one include, projected, with the unusable ones dropped."""
    resource = document.data
    entries = Included(document.included).related(
        resource, planned.include.relationship, schema=_IncludeResource
    )
    if not entries and resource is not None and resource.related_ids(planned.include.relationship):
        logger.warning(
            "includes.side_load.unresolved",
            extra={"include": planned.name, "relationship": planned.include.relationship},
        )
    return [
        model for entry in entries if (model := _project(entry=entry, planned=planned)) is not None
    ]


def _with_resource_id(entry: _IncludeResource) -> dict[str, object]:
    """A resource's `attributes`, with its JSON:API `id` folded in.

    `id` is a top-level member of a resource object, not one of its attributes, so a projection
    that wants to name the record it came from has to be handed it. It wins over any `id` already
    inside `attributes` — Backstop puts foreign keys there, not this resource's own identity —
    and a model that declares no `id` field drops it again under `extra="ignore"`.
    """
    return {**entry.attributes.model_dump(), "id": entry.id}


def _project(*, entry: _IncludeResource, planned: _PlannedInclude) -> BaseModel | None:
    """One related resource as the field's model, or `None` if unusable."""
    if entry.type != planned.include.resource_type:
        logger.warning(
            "includes.side_load.unexpected_type",
            extra={
                "include": planned.name,
                "expected_type": planned.include.resource_type,
                "actual_type": entry.type,
            },
        )
        return None
    # `included_resource` reads a present non-object `attributes` as `{}` so a strict schema
    # can still drop the entry. Include projections are not strict — every field is optional —
    # so that empty mapping would otherwise become a hollow record (id, no address). Treat it
    # as unreadable: one broken location must not look like a real one.
    if not entry.attributes.model_dump():
        logger.warning(
            "includes.side_load.unreadable",
            extra={"include": planned.name, "resource_type": planned.include.resource_type},
        )
        return None
    try:
        return planned.model.model_validate(_with_resource_id(entry))
    except ValidationError as exc:
        logger.warning(
            "includes.side_load.unreadable",
            extra={"include": planned.name, "resource_type": planned.include.resource_type},
            exc_info=exc,
        )
        return None
