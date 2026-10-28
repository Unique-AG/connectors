import hashlib
import logging
from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from typing import Literal
from typing import cast

import pydantic
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from mcp_observability import trace_arguments
from mcp_observability import trace_declarations as traced_module
from mcp_observability import traced
from mcp_observability import validate_trace_declarations
from mcp_observability.trace_declarations import tool_call_record

_CANARY = "zq-canary-value"
_LAST_NAME = "Doe"

type Status = Literal["open", "completed", "all"]


class Segment(StrEnum):
    PEOPLE = "people"


class Owner(pydantic.BaseModel):
    login: str


class Person(pydantic.BaseModel):
    last_name: str
    owner: Owner | None = None
    category_ids: tuple[str, ...] = ()
    nickname: str | None = None


class Organization(pydantic.BaseModel):
    name: str
    owner: Owner | None = None


class Tasks(pydantic.BaseModel):
    total: int
    rows: tuple[str, ...]


class Unsupported:
    pass


@pytest.fixture
def exporter(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(traced_module, "_tracer", provider.get_tracer("test"))
    return exporter


@pytest.fixture
def declarations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only what the test declares is validated."""
    monkeypatch.setattr(traced_module, "_declarations", [])


def _divided_by_zero(arguments: Mapping[str, object]) -> Mapping[str, object]:
    return {"x": len(arguments) / 0}


def _missing_attribute(value: object) -> Mapping[str, object]:
    return {"x": vars(value)["missing"]}


def _span(exporter: InMemorySpanExporter) -> ReadableSpan:
    (span,) = exporter.get_finished_spans()
    return span


def _hashed(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


class GetTasksQuery:
    @traced(
        arguments=("segment", "status", "since"),
        result=lambda tasks: {"total": tasks.total, "returned": len(tasks.rows)},
    )
    async def run(
        self, *, segment: Segment, status: Status = "all", since: date | None = None
    ) -> Tasks:
        del segment, status, since
        return Tasks(total=3, rows=("a", "b"))


class CreatePersonCommand:
    @traced(arguments=("person.category_ids",), identifying=("person.last_name",))
    def run(self, *, person: Person) -> str:
        return person.last_name


class FailingCommand:
    @traced(name="failing.command", arguments=("label",))
    async def run(self, *, label: str) -> None:
        raise KeyError(f"{label} {_CANARY}")


class TestTraced:
    async def test_opens_a_child_span_named_after_the_class_with_the_declared_values(
        self, exporter: InMemorySpanExporter
    ) -> None:
        result = await GetTasksQuery().run(segment=Segment.PEOPLE, since=date(2026, 10, 1))

        span = _span(exporter)
        assert result.total == 3
        assert span.name == "GetTasksQuery.run"
        assert span.attributes == {
            "input.segment": "people",
            "input.status": "all",
            "input.since": "2026-10-01",
            "result.total": 3,
            "result.returned": 2,
        }

    def test_a_function_span_is_named_after_the_function(
        self, exporter: InMemorySpanExporter
    ) -> None:
        @traced(arguments=("label",))
        def label_tasks(*, label: str) -> None:
            del label

        label_tasks(label="till")

        span = _span(exporter)
        assert span.name == "label_tasks"
        assert span.attributes == {"input.label": "till"}

    def test_a_sync_method_walks_paths_and_pseudonymises_identifying_values(
        self, exporter: InMemorySpanExporter
    ) -> None:
        created = CreatePersonCommand().run(
            person=Person(last_name=_LAST_NAME, category_ids=("7", "9"))
        )

        span = _span(exporter)
        assert created == _LAST_NAME
        assert span.name == "CreatePersonCommand.run"
        assert span.attributes == {
            "input.person.category_ids": ("7", "9"),
            "input.person.last_name": _hashed(_LAST_NAME),
        }

    async def test_a_failure_marks_the_span_without_its_message_and_is_reraised(
        self, exporter: InMemorySpanExporter
    ) -> None:
        with pytest.raises(KeyError, match=_CANARY):
            await FailingCommand().run(label="till")

        span = _span(exporter)
        assert span.name == "failing.command"
        assert span.status.status_code is StatusCode.ERROR
        assert span.status.description is None
        assert span.attributes == {"input.label": "till", "error.type": "KeyError"}
        assert span.events == ()

    async def test_a_lambda_computes_arguments(self, exporter: InMemorySpanExporter) -> None:
        class WindowQuery:
            @traced(arguments=lambda args: {"window_days": (args["end"] - args["start"]).days})
            async def run(self, *, start: date, end: date) -> None:
                del start, end

        await WindowQuery().run(start=date(2026, 10, 1), end=date(2026, 10, 8))

        span = _span(exporter)
        assert span.name == "WindowQuery.run"
        assert span.attributes == {"input.window_days": 7}

    async def test_a_lambda_keeps_identifying_values_pseudonymised(
        self, exporter: InMemorySpanExporter
    ) -> None:
        class LoginQuery:
            @traced(arguments=lambda args: {"kind": "login"}, identifying=("login",))
            async def run(self, *, login: str) -> None:
                del login

        await LoginQuery().run(login=_LAST_NAME)

        assert _span(exporter).attributes == {
            "input.kind": "login",
            "input.login": _hashed(_LAST_NAME),
        }


class TestCallTime:
    def test_a_path_through_none_is_skipped_silently(
        self, exporter: InMemorySpanExporter, caplog: pytest.LogCaptureFixture
    ) -> None:
        class Command:
            @traced(arguments=("person.owner.login", "person.nickname"))
            def run(self, *, person: Person) -> None:
                del person

        Command().run(person=Person(last_name=_LAST_NAME))

        assert _span(exporter).attributes == {}
        assert caplog.records == []

    @pytest.mark.parametrize(
        ("declared", "argument"),
        [
            ({"arguments": ("value",)}, "value"),
            ({"arguments": ("value.missing",)}, "value.missing"),
            ({"arguments": _divided_by_zero}, "lambda"),
            ({"result": _missing_attribute}, "result"),
        ],
    )
    def test_a_value_that_cannot_go_on_the_span_is_one_warning_and_the_call_succeeds(
        self,
        exporter: InMemorySpanExporter,
        caplog: pytest.LogCaptureFixture,
        declared: Mapping[str, object],
        argument: str,
    ) -> None:
        def command(*, value: object) -> str:
            del value
            return "done"

        wrapped = traced(**declared)(command)  # pyright: ignore[reportArgumentType]

        with caplog.at_level(logging.INFO):
            assert wrapped(value=Unsupported()) == "done"

        (record,) = caplog.records
        assert record.levelno == logging.WARNING
        assert record.getMessage() == "Trace attribute skipped"
        fields = cast("dict[str, object]", record.__dict__)
        assert str(fields["function"]).endswith("command")
        assert fields["argument"] == argument
        assert "error_type" in fields
        assert _span(exporter).attributes == {}


class TestTraceArguments:
    async def test_adds_to_the_current_span_and_the_tool_call_record(
        self, exporter: InMemorySpanExporter
    ) -> None:
        @trace_arguments("segment", identifying=("person.last_name",), result=lambda r: {"n": r})
        async def tool(*, segment: Segment, person: Person) -> int:
            del segment, person
            return 2

        tracer = traced_module._tracer  # pyright: ignore[reportPrivateUsage]
        with tool_call_record() as record, tracer.start_as_current_span("tools/call tool"):
            await tool(segment=Segment.PEOPLE, person=Person(last_name=_LAST_NAME))

        assert _span(exporter).attributes == {
            "tool.argument.segment": "people",
            "tool.argument.person.last_name": _hashed(_LAST_NAME),
            "tool.result.n": 2,
        }
        assert record == {"segment": "people", "person.last_name": _hashed(_LAST_NAME), "n": 2}

    def test_names_and_a_lambda_are_not_declared_together(self) -> None:
        with pytest.raises(AssertionError):
            trace_arguments("segment", lambda args: {})


@pytest.mark.usefixtures("declarations")
class TestValidation:
    def test_accepts_names_paths_unions_aliases_and_sequences(self) -> None:
        @traced(
            arguments=("segment", "status", "party.owner.login", "person.category_ids"),
            identifying=("person.last_name",),
        )
        def command(
            *, segment: Segment, status: Status, party: Person | Organization, person: Person
        ) -> None:
            del segment, status, party, person

        validate_trace_declarations()

    @pytest.mark.parametrize(
        ("arguments", "identifying", "reason"),
        [
            (("missing",), (), "missing: unknown argument"),
            (("person.missing",), (), "person.missing: unknown field missing"),
            (("party.name",), (), "party.name: unknown field name"),
            (("label.length",), (), "label.length: length is not a field"),
            (("person.owner",), (), "person.owner: unsupported value type"),
            ((), ("person.category_ids.count",), "is not a field"),
            ((), ("count",), "count: unsupported value type"),
        ],
    )
    def test_crashes_at_startup_naming_the_function_the_path_and_the_reason(
        self, arguments: tuple[str, ...], identifying: tuple[str, ...], reason: str
    ) -> None:
        @traced(arguments=arguments, identifying=identifying)
        def command(
            *, label: str, count: int, person: Person, party: Person | Organization
        ) -> None:
            del label, count, person, party

        with pytest.raises(AssertionError) as raised:
            validate_trace_declarations()

        assert "command" in str(raised.value)
        assert reason in str(raised.value)

    def test_crashes_on_an_annotation_it_cannot_resolve(self) -> None:
        @traced(arguments=("label",))
        def command(*, label: Undefined) -> None:  # noqa: F821  # pyright: ignore[reportUndefinedVariable, reportUnknownParameterType]
            del label

        with pytest.raises(AssertionError, match="unresolvable annotation"):
            validate_trace_declarations()
