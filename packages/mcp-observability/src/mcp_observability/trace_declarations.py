"""Arguments and results on spans, declared on the function so call sites stay as they are.

A declaration is a name, a dotted path into a pydantic model, or a lambda. Names and paths are
checked by `validate_trace_declarations` at startup; a lambda is the escape hatch for a computed
value, checked by neither the type checker (its parameter is `Never`) nor the startup check.
Tracing never fails the call: a value that cannot go on the span is skipped with one WARNING.
"""

import annotationlib
import functools
import inspect
import logging
import types
import typing
from collections.abc import Callable
from collections.abc import Coroutine
from collections.abc import Generator
from collections.abc import Mapping
from collections.abc import Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from enum import Enum
from typing import ClassVar
from typing import Literal
from typing import Never
from typing import Protocol
from typing import TypeAliasType
from typing import cast
from typing import overload

from opentelemetry import trace
from opentelemetry.trace import Span
from opentelemetry.trace import Status
from opentelemetry.trace import StatusCode
from opentelemetry.util.types import AttributeValue
from pydantic import BaseModel
from pydantic import ConfigDict

from mcp_observability.identifiable_value import IdentifiableValue
from mcp_observability.identifiable_value import identifiable_value

type ArgumentsLambda = Callable[[Mapping[str, Never]], Mapping[str, object]]
type ResultLambda = Callable[[Never], Mapping[str, object]]

_log = logging.getLogger("mcp_observability")
_tracer = trace.get_tracer("mcp_observability")
_SCALARS = (str, int, float, bool, Enum, date)
_SEQUENCES = (tuple, list, set, frozenset, Sequence)
# Declared tool-call values, which the tool-call middleware writes on its log lines. A mutable
# holder: FastMCP may run the tool in a copied context, where a `.set()` would be lost.
_tool_call: ContextVar[dict[str, AttributeValue] | None] = ContextVar(
    "mcp_observability_tool_call", default=None
)


class _Decorator(Protocol):
    @overload
    def __call__[**P, T](
        self, fn: Callable[P, Coroutine[object, object, T]], /
    ) -> Callable[P, Coroutine[object, object, T]]: ...
    @overload
    def __call__[**P, T](self, fn: Callable[P, T], /) -> Callable[P, T]: ...


def traced(
    *,
    name: str | None = None,
    arguments: Sequence[str] | ArgumentsLambda = (),
    identifying: Sequence[str] = (),
    result: ResultLambda | None = None,
) -> _Decorator:
    """Open a child span named `Class.method` or `function` unless `name` is given, with the
    declared arguments as `input.<name>` and the result as `result.<name>`. `identifying` values
    are pseudonymised."""

    def decorate(fn: Callable[..., object]) -> Callable[..., object]:
        declaration = _declare(fn, arguments, identifying, result)
        span_name = name or _span_name(fn)

        def around(bound: Mapping[str, object]) -> _Around:
            return _child_span(span_name, declaration, bound)

        return _wrapped(fn, declaration, around)

    return cast("_Decorator", decorate)


def trace_arguments(
    *arguments: str | ArgumentsLambda,
    identifying: Sequence[str] = (),
    result: ResultLambda | None = None,
) -> _Decorator:
    """Put a tool's declared arguments and result on FastMCP's `tools/call <tool>` span, as
    `tool.argument.<name>` and `tool.result.<name>`, and on the tool call's log lines. Goes under
    `@tool`. Opens no span.
    """
    lambdas = [argument for argument in arguments if callable(argument)]
    assert not lambdas or len(arguments) == 1, "Declare names and paths, or one lambda, not both"
    declared = lambdas[0] if lambdas else tuple(cast("tuple[str, ...]", arguments))

    def decorate(fn: Callable[..., object]) -> Callable[..., object]:
        declaration = _declare(fn, declared, identifying, result)

        def around(bound: Mapping[str, object]) -> _Around:
            return _on_tool_call(declaration, bound)

        return _wrapped(fn, declaration, around)

    return cast("_Decorator", decorate)


def validate_trace_declarations() -> None:
    """Crash at startup on a declaration that names an unknown argument or field, or whose value
    cannot go on a span. Runs after import, once every model a path walks through is defined."""
    problems = [problem for declaration in _declarations for problem in declaration.problems()]
    assert not problems, "Invalid trace declarations:\n" + "\n".join(problems)


@contextmanager
def tool_call_record() -> Generator[dict[str, AttributeValue]]:
    """What `@trace_arguments` declares during one tool call."""
    record: dict[str, AttributeValue] = {}
    token = _tool_call.set(record)
    try:
        yield record
    finally:
        _tool_call.reset(token)


class _Declaration(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    function: Callable[..., object]
    arguments: tuple[str, ...] | ArgumentsLambda
    identifying: tuple[str, ...]
    result: ResultLambda | None

    @property
    def qualname(self) -> str:
        return f"{self.function.__module__}.{self.function.__qualname__}"

    def argument_attributes(self, bound: Mapping[str, object]) -> dict[str, AttributeValue]:
        identifying = self._paths(bound, self.identifying, identifying=True)
        if callable(self.arguments):
            compute = cast("Callable[[Mapping[str, object]], Mapping[str, object]]", self.arguments)
            computed = self._converted(
                self._attempt("lambda", lambda: compute(bound)) or {}, "lambda"
            )
            return computed | identifying
        return self._paths(bound, self.arguments, identifying=False) | identifying

    def result_attributes(self, value: object) -> dict[str, AttributeValue]:
        if self.result is None:
            return {}
        compute = cast("Callable[[object], Mapping[str, object]]", self.result)
        return self._converted(self._attempt("result", lambda: compute(value)) or {}, "result")

    def problems(self) -> list[str]:
        try:
            hints = typing.get_type_hints(self.function)
        except Exception as error:  # noqa: BLE001
            return [f"{self.qualname}: unresolvable annotation ({type(error).__name__}: {error})"]
        parameters = set(
            inspect.signature(
                self.function, annotation_format=annotationlib.Format.FORWARDREF
            ).parameters
        ) - {"self"}
        declared = () if callable(self.arguments) else self.arguments
        return [
            f"{self.qualname}: {path}: {reason}"
            for path, identifying in [(path, False) for path in declared]
            + [(path, True) for path in self.identifying]
            if (reason := _path_problem(path, parameters, hints, identifying=identifying))
        ]

    def _paths(
        self, bound: Mapping[str, object], paths: Sequence[str], *, identifying: bool
    ) -> dict[str, AttributeValue]:
        attributes: dict[str, AttributeValue] = {}
        for path in paths:
            converted = self._attempt(path, lambda: _path_value(bound, path, identifying))  # noqa: B023
            if converted is not None:
                attributes[path] = converted
        return attributes

    def _converted(self, values: Mapping[str, object], source: str) -> dict[str, AttributeValue]:
        attributes: dict[str, AttributeValue] = {}
        for key, value in values.items():
            converted = self._attempt(source, lambda: _attribute_value(value, False))  # noqa: B023
            if converted is not None:
                attributes[key] = converted
        return attributes

    def _attempt[T](self, source: str, compute: Callable[[], T]) -> T | None:
        try:
            return compute()
        except Exception as error:  # noqa: BLE001
            _log.warning(
                "Trace attribute skipped",
                extra={
                    "function": self.qualname,
                    "argument": source,
                    "error_type": type(error).__qualname__,
                },
            )
            return None


type _Around = typing.ContextManager[Callable[[dict[str, AttributeValue]], None]]

_declarations: list[_Declaration] = []


def _declare(
    fn: Callable[..., object],
    arguments: Sequence[str] | ArgumentsLambda,
    identifying: Sequence[str],
    result: ResultLambda | None,
) -> _Declaration:
    declaration = _Declaration(
        function=fn,
        arguments=arguments if callable(arguments) else tuple(arguments),
        identifying=tuple(identifying),
        result=result,
    )
    _declarations.append(declaration)
    return declaration


def _wrapped(
    fn: Callable[..., object],
    declaration: _Declaration,
    around: Callable[[Mapping[str, object]], _Around],
) -> Callable[..., object]:
    # Annotations can name models defined below the class, which do not exist yet.
    signature = inspect.signature(fn, annotation_format=annotationlib.Format.FORWARDREF)

    def bound(args: tuple[object, ...], kwargs: dict[str, object]) -> Mapping[str, object]:
        arguments = signature.bind(*args, **kwargs)
        arguments.apply_defaults()
        values = cast("dict[str, object]", arguments.arguments)
        return {key: value for key, value in values.items() if key != "self"}

    if inspect.iscoroutinefunction(fn):
        call = cast("Callable[..., Coroutine[object, object, object]]", fn)

        @functools.wraps(fn)
        async def run_async(*args: object, **kwargs: object) -> object:
            with around(bound(args, kwargs)) as add_result:
                value = await call(*args, **kwargs)
                add_result(declaration.result_attributes(value))
                return value

        return run_async

    @functools.wraps(fn)
    def run(*args: object, **kwargs: object) -> object:
        with around(bound(args, kwargs)) as add_result:
            value = fn(*args, **kwargs)
            add_result(declaration.result_attributes(value))
            return value

    return run


@contextmanager
def _child_span(
    name: str, declaration: _Declaration, bound: Mapping[str, object]
) -> Generator[Callable[[dict[str, AttributeValue]], None]]:
    with _tracer.start_as_current_span(
        name, record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attributes(_prefixed(declaration.argument_attributes(bound), "input."))
        try:
            yield lambda attributes: span.set_attributes(_prefixed(attributes, "result."))
        except Exception as error:
            _mark_failed(span, error)
            raise


@contextmanager
def _on_tool_call(
    declaration: _Declaration, bound: Mapping[str, object]
) -> Generator[Callable[[dict[str, AttributeValue]], None]]:
    """The current span is FastMCP's `tools/call <tool>` span."""
    span = trace.get_current_span()
    record = _tool_call.get()

    def add(attributes: dict[str, AttributeValue], prefix: str) -> None:
        span.set_attributes(_prefixed(attributes, prefix))
        if record is not None:
            record.update(attributes)

    add(declaration.argument_attributes(bound), "tool.argument.")
    yield lambda attributes: add(attributes, "tool.result.")


def _mark_failed(span: Span, error: Exception) -> None:
    """No message: it can quote the payload."""
    span.set_status(Status(StatusCode.ERROR))
    span.set_attribute("error.type", type(error).__qualname__)


def _prefixed(attributes: Mapping[str, AttributeValue], prefix: str) -> dict[str, AttributeValue]:
    return {f"{prefix}{key}": value for key, value in attributes.items()}


def _span_name(fn: Callable[..., object]) -> str:
    """`Class.method` or `function`, without the `<locals>` of an enclosing function."""
    return fn.__qualname__.rpartition("<locals>.")[2]


def _path_value(bound: Mapping[str, object], path: str, identifying: bool) -> AttributeValue | None:
    """`None` when the path runs through `None`, which is skipped without a warning."""
    first, *rest = path.split(".")
    value = bound[first]
    for part in rest:
        if value is None:
            return None
        value = cast("object", getattr(value, part))
    return None if value is None else _attribute_value(value, identifying)


def _attribute_value(value: object, identifying: bool) -> AttributeValue:
    if isinstance(value, list | tuple | set | frozenset):
        items = [_scalar(item, identifying) for item in cast("Sequence[object]", value)]
        kinds = {type(item) for item in items}
        assert len(kinds) <= 1, f"mixed sequence of {sorted(kind.__name__ for kind in kinds)}"
        return cast("AttributeValue", tuple(items))
    return _scalar(value, identifying)


def _scalar(value: object, identifying: bool) -> str | int | float | bool:
    if identifying:
        assert isinstance(value, str), f"identifying value of type {type(value).__qualname__}"
        return str(identifiable_value(value))
    if isinstance(value, IdentifiableValue):
        return str(value)
    if isinstance(value, Enum):
        return _scalar(cast("object", value.value), identifying)
    if isinstance(value, date):
        return value.isoformat()
    assert isinstance(value, str | int | float | bool), f"unsupported {type(value).__qualname__}"
    return value


def _path_problem(
    path: str, parameters: set[str], hints: Mapping[str, object], *, identifying: bool
) -> str | None:
    first, *rest = path.split(".")
    if first not in parameters:
        return "unknown argument"
    if first not in hints:
        return "unannotated argument"
    candidates = _members(hints[first])
    for part in rest:
        models = [member for member in candidates if _is_model(member)]
        if not models or len(models) != len(candidates):
            return f"{part} is not a field: not a pydantic model"
        fields = [cast("type[BaseModel]", model).model_fields.get(part) for model in models]
        if any(field is None for field in fields):
            return f"unknown field {part}"
        candidates = [
            member for field in fields if field is not None for member in _members(field.annotation)
        ]
    if not candidates or not all(_supported(member, identifying) for member in candidates):
        return "unsupported value type"
    return None


def _members(annotation: object) -> list[object]:
    """The types `annotation` can be, aliases and `Annotated` unwrapped and `None` dropped."""
    if isinstance(annotation, TypeAliasType):
        return _members(cast("object", annotation.__value__))
    origin = typing.get_origin(annotation)
    arguments = _arguments(annotation)
    if origin is typing.Annotated:
        return _members(arguments[0])
    if origin is types.UnionType:
        return [
            member
            for argument in arguments
            if argument is not types.NoneType
            for member in _members(argument)
        ]
    return [annotation]


def _supported(member: object, identifying: bool) -> bool:
    origin = typing.get_origin(member)
    if isinstance(origin, type) and issubclass(origin, _SEQUENCES):
        elements = [element for element in _arguments(member) if element is not Ellipsis]
        return bool(elements) and all(_supported_scalar(e, identifying) for e in elements)
    return _supported_scalar(member, identifying)


def _supported_scalar(member: object, identifying: bool) -> bool:
    if typing.get_origin(member) is Literal:
        literals = _arguments(member)
        return all(isinstance(literal, str if identifying else _SCALARS) for literal in literals)
    return isinstance(member, type) and issubclass(member, str if identifying else _SCALARS)


def _arguments(annotation: object) -> tuple[object, ...]:
    return cast("tuple[object, ...]", typing.get_args(annotation))


def _is_model(member: object) -> bool:
    return isinstance(member, type) and issubclass(member, BaseModel)
