"""Every field a tool returns to the model has a description FastMCP can publish."""

import inspect
from collections.abc import Awaitable, Callable
from types import UnionType
from typing import Annotated, TypeAliasType, cast, get_args, get_origin, get_type_hints

from fastmcp.decorators import get_fastmcp_meta
from fastmcp.dependencies import Depends
from fastmcp.tools.function_tool import FunctionTool, ToolMeta
from pydantic import BaseModel

from backstop_mcp.server.tools import TOOLS
from tests.server.tools.helpers import object_dict


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
        "ActivityTagResponse",
        "AsOfResponse",
        "ContactEmailResponse",
        "CustomFieldDefinitionResponse",
        "CustomFieldEntityReferenceResponse",
        "CustomFieldGroupMemberResponse",
        "CustomFieldGroupParentResponse",
        "CustomFieldGroupResponse",
        "EmailRecordResponse",
        "EmploymentLinkResponse",
        "OpportunityResponse",
        "PartyCandidateResponse",
        "PersonResolvedResponse",
        "HoldingRowResponse",
        "MoneyResponse",
        "AccountRowResponse",
        "ProductInvestorsResolvedResponse",
        "TimeSeriesPointResponse",
        "TimeSeriesResolvedResponse",
        "ListSystemUsersResponse",
        "ScanCoverageResponse",
        "SearchActivitiesResolvedResponse",
        "SearchOpportunitiesResolvedResponse",
        "CapitalFlowsResolvedResponse",
        "ResolvedCustomFieldValueResponse",
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


# The marker `Depends(...)` leaves as a parameter default, taken from FastMCP's own export so a
# rename on their side surfaces here rather than quietly matching nothing.
_DEPENDS_MARKER = type(Depends(lambda: None))


def test_the_tools_do_declare_depends_params() -> None:
    """Guards the guard: with nothing to find, the leak test below passes vacuously."""
    declared = {name for fn in TOOLS for name in _depends_params(fn)}

    assert declared


def test_depends_params_are_not_in_the_published_input_schema() -> None:
    """Collaborators are resolved by FastMCP; the model must not see them as tool arguments."""
    leaked = [f"{fn.__name__}.{name}" for fn in TOOLS for name in _published_depends_params(fn)]

    assert leaked == []


def _depends_params(fn: Callable[..., Awaitable[object]]) -> list[str]:
    """The parameters this tool has FastMCP inject, read off the signature rather than listed."""
    return [
        name
        for name, parameter in inspect.signature(fn).parameters.items()
        if isinstance(cast("object", parameter.default), _DEPENDS_MARKER)
    ]


def _published_depends_params(fn: Callable[..., Awaitable[object]]) -> list[str]:
    meta = get_fastmcp_meta(fn)
    assert isinstance(meta, ToolMeta)
    tool = FunctionTool.from_function(fn, metadata=meta)
    published = set(object_dict(cast("object", tool.parameters.get("properties", {}))))
    return sorted(published.intersection(_depends_params(fn)))
