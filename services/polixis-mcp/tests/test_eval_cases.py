"""`evals/cases.yaml` stays runnable: every tool, argument, value and slot it names exists."""

from collections.abc import Iterator
from pathlib import Path
import re
from typing import ClassVar, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import TypeAdapter
import pytest
import yaml

SERVICE = Path(__file__).parent.parent
EVALS = SERVICE / "evals"
SLOT = re.compile(r"\{(\w+)\.(\w+)\}")
DOC_CASE = re.compile(r"^### (\d+)\. ", re.MULTILINE)


class Strict(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class ArgMatcher(Strict):
    present: bool | None = None
    absent: bool | None = None
    contains: list[str] | None = None
    one_of: list[str] | None = None
    min: int | None = None
    max: int | None = None


type ArgExpectation = ArgMatcher | int | str | list[str]


class ExpectedCall(Strict):
    tool: str
    args: dict[str, ArgExpectation] = Field(default_factory=dict)
    when: str | None = None


class ForbiddenCall(ExpectedCall):
    reason: str


class Expectation(Strict):
    first: str | None = None
    calls: list[ExpectedCall] = Field(default_factory=list)
    forbid: list[ForbiddenCall] = Field(default_factory=list)
    budget: int = Field(ge=1)
    answer: list[str] = Field(min_length=1)


class Turn(Strict):
    prompt: str
    expect: Expectation


class EntitySlot(Strict):
    type: Literal["PERSON", "ORGANIZATION", "ANY"]
    criteria: str
    fields: list[str] = Field(min_length=1)


class Case(Strict):
    id: str
    from_doc: int | None = None
    workflow: str
    entities: list[str] = Field(default_factory=list)
    turns: list[Turn] = Field(min_length=1)


class Defaults(Strict):
    answer: list[str]


class Suite(Strict):
    version: Literal[1]
    defaults: Defaults
    entities: dict[str, EntitySlot]
    cases: list[Case]


_TOOL_SURFACE = TypeAdapter(list[dict[str, object]])
_SCHEMA = TypeAdapter(dict[str, object])
_SCHEMAS = TypeAdapter(list[dict[str, object]])
_STRINGS = TypeAdapter(list[str])
_EXAMPLE_ENTITIES = TypeAdapter(dict[str, dict[str, str]])


@pytest.fixture(scope="module")
def suite() -> Suite:
    return Suite.model_validate(yaml.safe_load((EVALS / "cases.yaml").read_text()))


@pytest.fixture(scope="module")
def tool_arguments() -> dict[str, dict[str, dict[str, object]]]:
    """Each tool's arguments and their JSON schemas, as a client sees them."""
    surface = _TOOL_SURFACE.validate_json(
        (SERVICE / "tests/tool_surface.generated.json").read_text()
    )
    return {
        str(tool["name"]): {
            name: _SCHEMA.validate_python(schema)
            for name, schema in _SCHEMA.validate_python(
                _SCHEMA.validate_python(tool["inputSchema"])["properties"]
            ).items()
        }
        for tool in surface
    }


def allowed_values(schema: dict[str, object]) -> set[str] | None:
    """The enum an argument, or its list items, must come from; None when it takes any value."""
    if "enum" in schema:
        return set(_STRINGS.validate_python(schema["enum"]))
    for key in ("items", "anyOf"):
        nested = schema.get(key)
        for option in _SCHEMAS.validate_python(
            [nested] if isinstance(nested, dict) else nested or []
        ):
            if (values := allowed_values(option)) is not None:
                return values
    return None


def expected_values(expectation: ArgExpectation) -> list[str]:
    match expectation:
        case ArgMatcher(contains=contains, one_of=one_of):
            return [*(contains or []), *(one_of or [])]
        case str():
            return [expectation]
        case list():
            return expectation
        case int():
            return []


def every_call(case: Case) -> Iterator[ExpectedCall]:
    for turn in case.turns:
        yield from turn.expect.calls
        yield from turn.expect.forbid


def slots_in(case: Case) -> set[tuple[str, str]]:
    texts = [turn.prompt for turn in case.turns] + [
        value
        for call in every_call(case)
        for arg in call.args.values()
        for value in expected_values(arg)
    ]
    return {
        (slot, field)
        for text in texts
        for match in SLOT.finditer(text)
        for slot, field in [(match[1], match[2])]
    }


def test_case_ids_are_unique(suite: Suite) -> None:
    ids = [case.id for case in suite.cases]

    assert len(ids) == len(set(ids))


def test_cases_name_only_tools_and_arguments_the_server_has(
    suite: Suite, tool_arguments: dict[str, dict[str, dict[str, object]]]
) -> None:
    unknown = [
        f"{case.id}: {call.tool}({name})"
        for case in suite.cases
        for call in every_call(case)
        for name in call.args
        if name not in tool_arguments.get(call.tool, {})
    ] + [
        f"{case.id}: {tool}"
        for case in suite.cases
        for tool in [call.tool for call in every_call(case)]
        + [turn.expect.first for turn in case.turns]
        if tool is not None and tool not in tool_arguments
    ]

    assert unknown == []


def test_cases_expect_only_values_an_argument_accepts(
    suite: Suite, tool_arguments: dict[str, dict[str, dict[str, object]]]
) -> None:
    invalid = [
        f"{case.id}: {call.tool}({name}={value})"
        for case in suite.cases
        for call in every_call(case)
        for name, expectation in call.args.items()
        if (allowed := allowed_values(tool_arguments.get(call.tool, {}).get(name, {}))) is not None
        for value in expected_values(expectation)
        if not SLOT.search(value) and value not in allowed
    ]

    assert invalid == []


def test_cases_list_exactly_the_slots_they_use(suite: Suite) -> None:
    mismatched = [
        case.id
        for case in suite.cases
        if {slot for slot, _ in slots_in(case)} != set(case.entities)
    ]

    assert mismatched == []


def test_every_slot_a_case_uses_is_declared_with_its_field(suite: Suite) -> None:
    undeclared = [
        f"{case.id}: {slot}.{field}"
        for case in suite.cases
        for slot, field in sorted(slots_in(case))
        if slot not in suite.entities or field not in suite.entities[slot].fields
    ]

    assert undeclared == []


def test_every_declared_slot_is_used(suite: Suite) -> None:
    used = {slot for case in suite.cases for slot in case.entities}

    assert set(suite.entities) - used == set()


def test_budget_covers_every_required_call(suite: Suite) -> None:
    short = [
        case.id
        for case in suite.cases
        for turn in case.turns
        if turn.expect.budget < sum(call.when is None for call in turn.expect.calls)
    ]

    assert short == []


def test_example_entities_fill_every_slot_and_field(suite: Suite) -> None:
    example = _EXAMPLE_ENTITIES.validate_python(
        yaml.safe_load((EVALS / "entities.example.yaml").read_text())
    )

    assert {slot: set(values) for slot, values in example.items()} == {
        slot: set(declared.fields) for slot, declared in suite.entities.items()
    }


def test_every_case_in_the_use_case_doc_has_an_eval_case(suite: Suite) -> None:
    documented = {
        int(match[1])
        for match in DOC_CASE.finditer((SERVICE / "docs/agent-use-cases.md").read_text())
    }

    assert {case.from_doc for case in suite.cases if case.from_doc is not None} == documented
