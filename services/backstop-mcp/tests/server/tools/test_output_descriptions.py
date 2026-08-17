"""Every field a tool returns to the model has a description FastMCP can publish."""

from types import UnionType
from typing import Annotated, TypeAliasType, cast, get_args, get_origin, get_type_hints

from pydantic import BaseModel

from backstop_mcp.server.tools.registry import TOOLS


def _is_model(annotation: object) -> type[BaseModel] | None:
    if not isinstance(annotation, type):
        return None
    try:
        return annotation if issubclass(annotation, BaseModel) else None
    except TypeError:
        return None


def _args(annotation: object) -> tuple[object, ...]:
    return cast(tuple[object, ...], get_args(annotation))


def _collect_models(annotation: object, seen: set[type[BaseModel]]) -> None:
    if annotation is None:
        return
    if isinstance(annotation, TypeAliasType):
        _collect_models(cast(object, annotation.__value__), seen)
        return
    origin: object = get_origin(annotation)
    if origin is UnionType or getattr(origin, "__name__", "") == "Union":
        for arg in _args(annotation):
            _collect_models(arg, seen)
        return
    if origin is Annotated:
        inner = _args(annotation)
        if inner:
            _collect_models(inner[0], seen)
        return
    if origin is not None:
        model = _is_model(origin)
        if model is not None:
            _add_model(model, seen)
        for arg in _args(annotation):
            _collect_models(arg, seen)
        return
    model = _is_model(annotation)
    if model is not None:
        _add_model(model, seen)


def _add_model(model: type[BaseModel], seen: set[type[BaseModel]]) -> None:
    if model in seen:
        return
    seen.add(model)
    for field in model.model_fields.values():
        _collect_models(field.annotation, seen)


def _tool_return_models() -> set[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    for fn in TOOLS:
        return_type: object = get_type_hints(fn)["return"]  # pyright: ignore[reportAny]
        _collect_models(return_type, seen)
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
