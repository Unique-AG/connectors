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
_ENTRY_KEYS = {"provenance", "evidence", "asks_user", "chain", "must_not", "note"}
_STEP_KEYS = {"tool", "any_of", "optional", "repeat", "args", "uses"}
_APPROVAL_PHRASE = "asked to approve"


@dataclass(frozen=True)
class _Scenario:
    name: str
    ids: tuple[str, ...]
    tags: frozenset[str]
    steps: tuple[str, ...]


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


def _step_tools(step: Mapping[str, object]) -> list[str]:
    if "any_of" in step:
        return [str(name) for name in _list(step["any_of"])]
    return [str(step["tool"])]


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
        return set.union(*found) if found and all(found) else set()

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
        assert (chain == []) == ("known-gap" in scenario.tags), (
            "a known gap has no chain, and a chain means the gap is not known"
        )
        for step in map(_object, chain):
            assert set(step) <= _STEP_KEYS, set(step) - _STEP_KEYS
            assert ("tool" in step) != ("any_of" in step), "a step has `tool` or `any_of`"
            assert not ("any_of" in step and {"args", "uses"} & set(step)), (
                "`args` and `uses` belong to a step with one tool"
            )

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
            for step in map(_object, _list(entry["chain"])):
                if "tool" not in step or str(step["tool"]) not in tools:
                    continue
                schema = tools[str(step["tool"])].input_schema
                accepted = set(_object(_object(schema)["properties"]))
                given = set(_object(step.get("args", {}))) | set(_object(step.get("uses", {})))
                if not given <= accepted:
                    problems.append(
                        f"{scenario_id}: {step['tool']} has no argument {sorted(given - accepted)}"
                        + f", it has {sorted(accepted)}"
                    )
                for name, value in _object(step.get("args", {})).items():
                    allowed = _allowed_values(_object(schema), name)
                    if allowed and value not in allowed:
                        problems.append(
                            f"{scenario_id}: {step['tool']} takes {name} from {sorted(allowed)}"
                            + f", not {value!r}"
                        )

        assert problems == []


class _Generator(Protocol):
    """The part of `scripts/render-use-cases.py` this file drives. Loaded by path because the
    filename carries hyphens."""

    TARGET: pathlib.Path

    @staticmethod
    def render() -> str: ...


def _generator() -> _Generator:
    path = _SERVICE_ROOT / "scripts" / "render-use-cases.py"
    spec = importlib.util.spec_from_file_location("render_use_cases", path)
    assert spec is not None and spec.loader is not None, f"{path.name} could not be loaded"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_Generator", cast("object", module))


class TestThePageForReaders:
    def test_it_is_what_the_generator_produces(self) -> None:
        generator = _generator()

        assert generator.TARGET.read_text() == generator.render(), (
            "docs/use-cases.md is stale: run scripts/render-use-cases.py and commit the result"
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
