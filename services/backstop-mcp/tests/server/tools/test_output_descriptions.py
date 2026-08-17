"""Every field a tool returns to the model has a description FastMCP can publish."""

from types import UnionType
from typing import Annotated, TypeAliasType, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel

from backstop_mcp.server.tools.registry import TOOLS


def _is_model(annotation: object) -> bool:
    if not isinstance(annotation, type):
        return False
    try:
        return issubclass(annotation, BaseModel)
    except TypeError:
        return False


def _collect_models(annotation: object, seen: set[type[BaseModel]]) -> None:
    if annotation is None:
        return
    if isinstance(annotation, TypeAliasType):
        _collect_models(annotation.__value__, seen)
        return
    origin = get_origin(annotation)
    if origin is UnionType or origin is Union:
        for arg in get_args(annotation):
            _collect_models(arg, seen)
        return
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            _collect_models(args[0], seen)
        return
    if origin is not None:
        if _is_model(origin):
            _add_model(origin, seen)
        for arg in get_args(annotation):
            _collect_models(arg, seen)
        return
    if _is_model(annotation):
        _add_model(annotation, seen)


def _add_model(model: type[BaseModel], seen: set[type[BaseModel]]) -> None:
    if model in seen:
        return
    seen.add(model)
    for field in model.model_fields.values():
        _collect_models(field.annotation, seen)


def _tool_return_models() -> set[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    for fn in TOOLS:
        _collect_models(get_type_hints(fn)["return"], seen)
    return seen


def test_the_walker_reaches_nested_payload_models() -> None:
    names = {model.__name__ for model in _tool_return_models()}
    assert {
        "ActivityDetailResponse",
        "ActivityRecordResponse",
        "AsOf",
        "ContactEmailResponse",
        "CustomFieldDefinition",
        "EmailRecordResponse",
        "EmploymentLinkResponse",
        "OpportunityResponse",
        "PartyCandidateResponse",
        "PersonResolvedResponse",
        "ResolvedPartyResponse",
    } <= names


def test_every_tool_response_field_is_described() -> None:
    missing = [
        f"{model.__name__}.{name}"
        for model in sorted(_tool_return_models(), key=lambda item: item.__name__)
        for name, field in model.model_fields.items()
        if not field.description
    ]
    assert missing == []
