"""The use cases in `features/`, and the tool chains that go with them.

A `NN-name.feature` file states what a user expects, in business words. A `NN-name.calls.yaml` file
beside it states which tools the assistant calls to meet that expectation. Each scenario carries a
permanent `@uc-NN-MM` tag, and the sidecar uses that tag as its key.

What this file checks is that the two files describe the same scenarios, and that a chain names
only tools and arguments that the server really has. A renamed tool or argument fails here, in the
chain that used it. What it cannot see is whether a model chooses the chain. That is a test with a
model, and `provenance` says which chains came from real prod sessions and which were drafted.
"""

import importlib.util
import pathlib
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

import pytest
import yaml
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from gherkin.parser import Parser

from office_365_mcp.tools import TOOL_NAMES

_SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FEATURES = _SERVICE_ROOT / "features"
_PAGE_BEGIN = "<!-- use-cases:begin -->"
_PAGE_END = "<!-- use-cases:end -->"
_FEATURE_FILES = sorted(_FEATURES.glob("*.feature"))
_ID = re.compile(r"uc-(?P<file>\d\d)-(?P<number>\d\d)")
_PROVENANCE = {"observed", "drafted"}
_STATUSES = {"untested", "working", "partly", "gap"}
_KINDS = {"tool", "parameter", "description", "preset", "graph", "unknown"}
_BLOCKER_KEYS = {"kind", "tool", "text", "user"}
_ENTRY_KEYS = {
    "status",
    "ask",
    "blocker",
    "provenance",
    "evidence",
    "asks_user",
    "chain",
    "must_not",
    "note",
    "cassette",
    "variants",
}
_RUNNER_STEP_KEYS = {"pick", "fault", "expect", "approval", "bind"}
_STEP_KEYS = {"tool", "any_of", "optional", "repeat", "args", "uses", *_RUNNER_STEP_KEYS}
_APPROVALS = {"yes", "no", "silent", "unanswered"}
_FAULTS = {"graph", "transport", "input"}
_EXPECT_KEYS = {"tool_error", "result", "graph_calls", "retry_sleeps"}
_GRAPH_CALL = re.compile(r"(GET|POST|PUT|PATCH|DELETE) /\S+")
_E2E = _SERVICE_ROOT / "tests" / "e2e"
_APPROVAL_PHRASE = "asked to approve"
_MAX_STEPS = 5
_NOT_OBSERVABLE = re.compile(r"\b(?:(?:asks?|asked) Microsoft|unless)\b", re.IGNORECASE)
_TECHNICAL_WORDS = re.compile(
    r"\b("
    + "|".join(
        (
            "click|button|field|dropdown|modal|url|css|endpoint|payload|requests?|responses?",
            "status code|json|rest|database|sql|https?|api|server|cache|queue|microservice",
            "container|pipeline|invoke|assert|navigate|scroll|submit",
        )
    )
    + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Scenario:
    name: str
    ids: tuple[str, ...]
    tags: frozenset[str]
    steps: tuple[str, ...]
    keywords: tuple[str, ...]
    kinds: tuple[str, ...]


def _object(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping), f"expected a mapping, got {type(value).__name__}"
    return cast("Mapping[str, object]", value)


def _list(value: object) -> Sequence[object]:
    assert isinstance(value, list), f"expected a list, got {type(value).__name__}"
    return cast("Sequence[object]", value)


def _scenario_nodes(node: Mapping[str, object]) -> Iterator[Mapping[str, object]]:
    for child in _list(node["children"]):
        entry = _object(child)
        if "rule" in entry:
            yield from _scenario_nodes(_object(entry["rule"]))
        elif "scenario" in entry:
            yield _object(entry["scenario"])


def _scenarios(feature_file: pathlib.Path) -> list[_Scenario]:
    document = _object(Parser().parse(feature_file.read_text()))
    found: list[_Scenario] = []
    for node in _scenario_nodes(_object(document["feature"])):
        tags = frozenset(str(_object(tag)["name"]).removeprefix("@") for tag in _list(node["tags"]))
        found.append(
            _Scenario(
                name=str(node["name"]),
                ids=tuple(sorted(tag for tag in tags if _ID.fullmatch(tag))),
                tags=tags,
                steps=tuple(str(_object(step)["text"]) for step in _list(node["steps"])),
                keywords=tuple(str(_object(s)["keyword"]).strip() for s in _list(node["steps"])),
                kinds=tuple(str(_object(s)["keywordType"]) for s in _list(node["steps"])),
            )
        )
    return found


def _sidecar(feature_file: pathlib.Path) -> Mapping[str, object]:
    return _object(
        cast("object", yaml.safe_load(feature_file.with_suffix(".calls.yaml").read_text()))
    )


def _entries() -> list[tuple[str, str]]:
    return [
        (feature_file.stem, scenario_id)
        for feature_file in _FEATURE_FILES
        if feature_file.with_suffix(".calls.yaml").exists()
        for scenario_id in _sidecar(feature_file)
    ]


def _stem(path: pathlib.Path) -> str:
    return path.stem


def _feature_named(stem: str) -> pathlib.Path:
    return _FEATURES / f"{stem}.feature"


def _scenario_with_id(stem: str, scenario_id: str) -> _Scenario:
    return next(s for s in _scenarios(_feature_named(stem)) if scenario_id in s.ids)


def _style_problems(scenario: _Scenario) -> list[str]:
    problems: list[str] = []
    if scenario.kinds.count("Action") != 1:
        problems.append(f"it has {scenario.kinds.count('Action')} When steps, and needs exactly 1")
    if len(scenario.steps) > _MAX_STEPS:
        problems.append(f"it has {len(scenario.steps)} steps, and {_MAX_STEPS} is the most")
    for first, second in zip(scenario.keywords, scenario.keywords[1:], strict=False):
        if first == second and first in {"Given", "When", "Then"}:
            problems.append(f"it repeats {first}, and And or But continue a step")
    action = scenario.kinds.index("Action") if "Action" in scenario.kinds else len(scenario.steps)
    for text in scenario.steps[action + 1 :]:
        if _NOT_OBSERVABLE.search(text):
            problems.append(
                f"a Then step states a call that Mia cannot see, or a condition: {text!r}"
            )
    if len(scenario.tags & {"happy", "unhappy"}) != 1:
        problems.append("it needs exactly one tag of @happy and @unhappy")
    found = _TECHNICAL_WORDS.finditer(" ".join(scenario.steps))
    words = sorted({match.group(0).lower() for match in found})
    if words:
        problems.append(f"its steps use technical words {words}")
    return problems


def _step_tools(step: Mapping[str, object]) -> list[str]:
    if "any_of" in step:
        return [str(name) for name in _list(step["any_of"])]
    return [str(step["tool"])]


def _cassettes(entry: Mapping[str, object]) -> list[str]:
    variants = map(_object, _object(entry.get("variants", {})).values())
    named = [entry.get("cassette"), *(variant.get("cassette") for variant in variants)]
    return [str(name) for name in named if name is not None]


def _run_steps(entry: Mapping[str, object]) -> Iterator[Mapping[str, object]]:
    chain = [_object(step) for step in _list(entry["chain"])]
    yield from chain
    for variant in map(_object, _object(entry.get("variants", {})).values()):
        assert "cassette" in entry or "cassette" in variant, "a run names a cassette"
        for key, override in cast("Mapping[object, object]", variant).items():
            if key != "cassette":
                assert key in range(1, len(chain) + 1), f"a variant names step {key!r}"
                assert set(_object(override)) <= _RUNNER_STEP_KEYS, set(_object(override))
                yield {**chain[cast("int", key) - 1], **_object(override)}


def _runner_problems(step: Mapping[str, object]) -> list[str]:
    fault, expect = _object(step.get("fault", {})), _object(step.get("expect", {}))
    calls = _object(expect.get("graph_calls", {})).items()
    rules = [
        (
            "`pick` names a tool of `any_of`",
            step.get("pick") in [None, *_list(step.get("any_of", []))],
        ),
        ("`bind` needs `tool` or `pick`", "tool" in step or "pick" in step or "bind" not in step),
        (
            "`approval` is a quoted yes, no, silent, or unanswered",
            step.get("approval", "yes") in _APPROVALS,
        ),
        ("a fault is one of graph, transport, input", not fault or len(_FAULTS & set(fault)) == 1),
        ("a fault holds no key but those, at, and times", set(fault) <= _FAULTS | {"at", "times"}),
        (f"`expect` holds only {sorted(_EXPECT_KEYS)}", set(expect) <= _EXPECT_KEYS),
        (
            "`graph_calls` maps METHOD /path to a count",
            all(_GRAPH_CALL.fullmatch(call) and isinstance(count, int) for call, count in calls),
        ),
    ]
    return [rule for rule, holds in rules if not holds]


def _allowed_values(schema: Mapping[str, object], argument: str) -> set[object]:
    properties = _object(schema.get("properties", {}))
    if argument not in properties:
        return set()
    definitions = _object(schema.get("$defs", {}))

    def values(node: Mapping[str, object]) -> set[object]:
        if "$ref" in node:
            return values(_object(definitions[str(node["$ref"]).rsplit("/", 1)[-1]]))
        if "enum" in node:
            return set(_list(node["enum"]))
        if "const" in node:
            return {node["const"]}
        branches = [_object(branch) for branch in _list(node.get("anyOf", []))]
        found = [values(branch) for branch in branches if branch.get("type") != "null"]
        merged: set[object] = set()
        for allowed in found:
            merged |= allowed
        return merged if all(found) else set()

    return values(_object(properties[argument]))


class TestFeatureFiles:
    def test_there_are_features_to_check(self) -> None:
        assert _FEATURE_FILES, "no .feature file under features/, so every check below is vacuous"

    def test_each_feature_has_a_sidecar_and_each_sidecar_a_feature(self) -> None:
        features = {path.stem for path in _FEATURES.glob("*.feature")}
        sidecars = {
            path.name.removesuffix(".calls.yaml") for path in _FEATURES.glob("*.calls.yaml")
        }

        assert features == sidecars

    @pytest.mark.parametrize("feature_file", _FEATURE_FILES, ids=_stem)
    def test_each_scenario_has_one_id_that_starts_with_its_file_number(
        self, feature_file: pathlib.Path
    ) -> None:
        file_number = feature_file.name.split("-", maxsplit=1)[0]
        scenarios = _scenarios(feature_file)

        for scenario in scenarios:
            assert len(scenario.ids) == 1, f"{scenario.name!r} needs exactly one @uc-NN-MM tag"
            match = _ID.fullmatch(scenario.ids[0])
            assert match is not None and match["file"] == file_number, scenario.name
        all_ids = [scenario.ids for scenario in scenarios]
        assert len(set(all_ids)) == len(all_ids), "two scenarios share an id"

    @pytest.mark.parametrize("feature_file", _FEATURE_FILES, ids=_stem)
    def test_no_feature_names_a_tool(self, feature_file: pathlib.Path) -> None:
        words = set(re.findall(r"[a-z][a-z0-9_]+", feature_file.read_text()))

        assert words & set(TOOL_NAMES) == set(), (
            "a feature states what a user expects, so the tools belong in the sidecar"
        )


class TestGherkinStyle:
    @pytest.mark.parametrize(("stem", "scenario_id"), _entries())
    def test_a_scenario_follows_the_gherkin_checklist(self, stem: str, scenario_id: str) -> None:
        assert _style_problems(_scenario_with_id(stem, scenario_id)) == []


class TestSidecars:
    @pytest.mark.parametrize("feature_file", _FEATURE_FILES, ids=_stem)
    def test_a_sidecar_has_exactly_the_scenarios_of_its_feature(
        self, feature_file: pathlib.Path
    ) -> None:
        ids = {scenario.ids[0] for scenario in _scenarios(feature_file)}

        assert set(_sidecar(feature_file)) == ids

    @pytest.mark.parametrize(("stem", "scenario_id"), _entries())
    def test_an_entry_has_the_documented_shape(self, stem: str, scenario_id: str) -> None:
        entry = _object(_sidecar(_feature_named(stem))[scenario_id])
        scenario = _scenario_with_id(stem, scenario_id)

        assert set(entry) <= _ENTRY_KEYS, set(entry) - _ENTRY_KEYS
        assert entry["provenance"] in _PROVENANCE
        assert ("evidence" in entry) or entry["provenance"] == "drafted", (
            "an observed chain names its evidence"
        )
        assert isinstance(entry["asks_user"], bool)
        chain = _list(entry["chain"])
        assert entry["status"] in _STATUSES
        assert (chain == []) == (entry["status"] == "gap"), (
            "a gap has no chain, and a chain means the gap is not known"
        )
        assert not {"working", "known-gap", "seen-failing"} & scenario.tags, (
            "status lives in the sidecar"
        )
        ask = entry["ask"]
        assert isinstance(ask, str) and ask.strip(), "every scenario has a prompt in `ask`"
        assert not [name for name in TOOL_NAMES if name in ask], "an ask names no tool"
        assert ("blocker" in entry) == (entry["status"] in {"partly", "gap"}), (
            "a blocker is there when status is partly or gap, and only then"
        )
        if blocker := entry.get("blocker"):
            blocker = _object(blocker)
            assert set(blocker) <= _BLOCKER_KEYS and blocker["kind"] in _KINDS
            assert str(blocker["text"]).strip() and str(blocker["user"]).strip()
            assert not [name for name in TOOL_NAMES if name in str(blocker["user"])], (
                "the user text of a blocker names no tool"
            )
            assert blocker.get("tool", next(iter(TOOL_NAMES))) in TOOL_NAMES
        for step in map(_object, chain):
            assert set(step) <= _STEP_KEYS, set(step) - _STEP_KEYS
            assert ("tool" in step) != ("any_of" in step), "a step has `tool` or `any_of`"
            assert not ("any_of" in step and {"args", "uses"} & set(step)), (
                "`args` and `uses` belong to a step with one tool"
            )
        for name in _cassettes(entry):
            assert (_E2E / "cassettes" / f"{name}.json").is_file(), f"no cassette {name}"
        assert [problem for step in _run_steps(entry) for problem in _runner_problems(step)] == []

    @pytest.mark.parametrize(("stem", "scenario_id"), _entries())
    def test_a_scenario_that_asks_for_approval_says_so(self, stem: str, scenario_id: str) -> None:
        entry = _object(_sidecar(_feature_named(stem))[scenario_id])
        scenario = _scenario_with_id(stem, scenario_id)

        if any(_APPROVAL_PHRASE in step for step in scenario.steps):
            assert entry["asks_user"] is True

    @pytest.mark.parametrize("feature_file", _FEATURE_FILES, ids=_stem)
    async def test_a_chain_names_only_tools_and_arguments_that_exist(
        self, feature_file: pathlib.Path, every_tool: Client[FastMCPTransport]
    ) -> None:
        tools = {tool.name: tool for tool in await every_tool.list_tools()}
        problems: list[str] = []

        for scenario_id, raw_entry in _sidecar(feature_file).items():
            entry = _object(raw_entry)
            used = [
                *(str(name) for name in _list(entry.get("must_not", []))),
                *(name for step in _list(entry["chain"]) for name in _step_tools(_object(step))),
            ]
            problems += [
                f"{scenario_id}: no tool named {name}" for name in used if name not in tools
            ]
            for step in _run_steps(entry):
                tool = str(step.get("pick", step.get("tool")))
                if tool not in tools:
                    continue
                schema = tools[tool].input_schema
                accepted = set(_object(_object(schema)["properties"]))
                given = {
                    *_object(step.get("args", {})),
                    *_object(step.get("uses", {})),
                    *_object(step.get("bind", {})),
                    *_object(_object(step.get("fault", {})).get("input", {})),
                }
                if not given <= accepted:
                    problems.append(
                        f"{scenario_id}: {tool} has no argument {sorted(given - accepted)}"
                        + f", it has {sorted(accepted)}"
                    )
                for name, value in _object(step.get("args", {})).items():
                    allowed = _allowed_values(_object(schema), name)
                    if allowed and value not in allowed:
                        problems.append(
                            f"{scenario_id}: {step['tool']} takes {name} "
                            + f"from {sorted(allowed, key=str)}, not {value!r}"
                        )

        assert problems == []


class TestTheScenarioRuns:
    def test_every_cassette_and_fixture_is_used(self) -> None:
        sidecars = [_sidecar(feature_file) for feature_file in _FEATURE_FILES]
        named = {name for s in sidecars for e in s.values() for name in _cassettes(_object(e))}
        cassettes = sorted((_E2E / "cassettes").glob("*.json"))
        text = "".join(path.read_text() for path in [*cassettes, *_FEATURES.glob("*.calls.yaml")])
        fixtures = sorted((_E2E / "fixtures").iterdir())

        problems = [
            f"no sidecar names cassettes/{p.name}" for p in cassettes if p.stem not in named
        ]
        problems += [f"nothing uses fixtures/{p.name}" for p in fixtures if p.name not in text]
        assert problems == []


class _Generator(Protocol):
    """The part of `scripts/render-use-cases.py` this file drives. Loaded by path because the
    filename carries hyphens."""

    TARGET: pathlib.Path
    STATUS: pathlib.Path

    @staticmethod
    def coverage() -> dict[str, tuple[int, int]]: ...

    @staticmethod
    def exceptions() -> dict[str, Mapping[str, object]]: ...

    @staticmethod
    def render() -> str: ...

    @staticmethod
    def render_status() -> str: ...


def _generator() -> _Generator:
    path = _SERVICE_ROOT / "scripts" / "render-use-cases.py"
    spec = importlib.util.spec_from_file_location("render_use_cases", path)
    assert spec is not None and spec.loader is not None, f"{path.name} could not be loaded"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_Generator", cast("object", module))


class TestToolCoverage:
    def test_every_tool_has_a_happy_and_an_unhappy_scenario_or_a_reason(self) -> None:
        generator = _generator()
        reasons = generator.exceptions()
        problems: list[str] = []
        for tool, (happy, unhappy) in generator.coverage().items():
            exempt = str(reasons.get(tool, {}).get("exempt", ""))
            if not happy and exempt not in {"happy", "both"}:
                problems.append(f"{tool} has no happy scenario")
            if not unhappy and exempt not in {"unhappy", "both"}:
                problems.append(f"{tool} has no unhappy scenario")
            if happy and unhappy and exempt:
                problems.append(f"{tool} has both kinds, so its exception is stale")
        assert problems == []

    def test_an_exception_names_a_real_tool_with_a_reason(self) -> None:
        for tool, entry in _generator().exceptions().items():
            assert tool in TOOL_NAMES, f"{tool} is not a tool"
            assert entry.get("exempt") in {"happy", "unhappy", "both"}, tool
            assert str(entry.get("reason", "")).strip(), f"{tool} needs a reason"


class TestThePageForReaders:
    def test_it_is_what_the_generator_produces(self) -> None:
        generator = _generator()

        assert generator.TARGET.read_text() == generator.render(), (
            "docs/use-cases.md is stale: run scripts/render-use-cases.py and commit the result"
        )

    def test_the_status_page_is_what_the_generator_produces(self) -> None:
        generator = _generator()

        assert generator.STATUS.read_text() == generator.render_status(), (
            "features/STATUS.md is stale: run scripts/render-use-cases.py and commit the result"
        )

    def test_it_holds_no_html_tag_outside_a_code_span(self) -> None:
        generated = _generator().render().split(_PAGE_BEGIN)[1].split(_PAGE_END)[0]
        outside_code = re.sub(r"`[^`]*`", "", generated)

        assert re.findall(r"<[A-Za-z/!][^>]*>", outside_code) == [], (
            "the publisher reads this as a tag and fails on the page"
        )

    def test_it_is_held_back_from_confluence_until_it_has_a_page(self) -> None:
        docs = _generator().TARGET.parent
        page = (docs / "use-cases.md").read_text()
        ignored = (docs / ".mdignore").read_text().split() if (docs / ".mdignore").exists() else []

        assert "confluence-page-id" in page or "use-cases.md" in ignored, (
            "the publisher reads every Markdown file in docs/ and creates a page for one that has "
            "no page id. Give the page an id, or list it in docs/.mdignore."
        )
