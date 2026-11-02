"""Every scenario in `features/` has a test or an explained reason, and the list of scenarios that
have neither yet (`features/PENDING.txt`) only gets shorter. `features/README.md`, "Testing a
scenario", has the keys."""

import ast
import pathlib
from collections.abc import Mapping
from typing import cast

import pytest
import yaml

_SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FEATURES = _SERVICE_ROOT / "features"
_PENDING = _FEATURES / "PENDING.txt"
_RUNNER = "tests/e2e/test_scenarios.py::test_the_scenario_runs_as_its_sidecar_says"
_NO_TEST_KINDS = ("assistant", "human", "limit")


def _entries() -> dict[str, Mapping[str, object]]:
    return {
        scenario_id: cast("Mapping[str, object]", entry)
        for sidecar in sorted(_FEATURES.glob("*.calls.yaml"))
        for scenario_id, entry in cast(
            "Mapping[str, object]", yaml.safe_load(sidecar.read_text())
        ).items()
    }


def _pending() -> set[str]:
    return set(_PENDING.read_text().split()) if _PENDING.exists() else set()


def _runs(scenario_id: str, entry: Mapping[str, object]) -> set[str]:
    named = cast("Mapping[str, object]", entry.get("variants", {}))
    own: set[str] = {scenario_id} if "fixture" in entry else set()
    return own | {f"{scenario_id}/{name}" for name in named}


def _defines(source: pathlib.Path, names: list[str]) -> bool:
    scope: ast.AST = ast.parse(source.read_text())
    for name in names:
        found = next(
            (
                node
                for node in ast.iter_child_nodes(scope)
                if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == name
            ),
            None,
        )
        if found is None:
            return False
        scope = found
    return True


def _node_problems(scenario_id: str, entry: Mapping[str, object], node: object) -> list[str]:
    if not isinstance(node, str):
        return [f"{scenario_id}: {node!r} is not a node id"]
    base, _, bracket = node.partition("[")
    path, *names = base.split("::")
    if not (_SERVICE_ROOT / path).is_file() or not names:
        return [f"{scenario_id}: {node} names no test file or no test in it"]
    if not _defines(_SERVICE_ROOT / path, names):
        return [f"{scenario_id}: {node} names a class or function that the file does not define"]
    if bracket and (base != _RUNNER or bracket.removesuffix("]") not in _runs(scenario_id, entry)):
        return [
            f"{scenario_id}: {node} has a bracket, and only a run of this scenario may have one"
        ]
    return []


def _problems(scenario_id: str, entry: Mapping[str, object], pending: set[str]) -> list[str]:
    keys = [key for key in ("tests", "no_test") if key in entry]
    if len(keys) == 2:
        return [f"{scenario_id}: has both `tests` and `no_test`"]
    if not keys:
        return [] if scenario_id in pending else [f"{scenario_id}: has no `tests` or `no_test`"]
    if scenario_id in pending:
        return [f"{scenario_id}: has `{keys[0]}`, so delete its line in PENDING.txt"]
    if keys[0] == "no_test":
        kind, _, reason = str(entry["no_test"]).partition(":")
        known = kind in _NO_TEST_KINDS and reason.strip()
        return (
            [] if known else [f"{scenario_id}: `no_test` is `<{'|'.join(_NO_TEST_KINDS)}>: <why>`"]
        )
    tests = entry["tests"]
    if not isinstance(tests, list) or not tests:
        return [f"{scenario_id}: `tests` is a list with at least one node id"]
    nodes = cast("list[object]", tests)
    problems = [p for node in nodes for p in _node_problems(scenario_id, entry, node)]
    if _runs(scenario_id, entry) and not any(str(node).startswith(f"{_RUNNER}[") for node in nodes):
        problems.append(f"{scenario_id}: has a run, so `tests` lists its runner node id")
    return problems


class TestEveryScenarioHasATestOrAReason:
    def test_the_sidecars_say_so_or_the_scenario_is_pending(self) -> None:
        pending = _pending()

        problems = [p for i, e in _entries().items() for p in _problems(i, e, pending)]

        assert problems == []

    def test_the_pending_list_names_only_scenarios_that_exist(self) -> None:
        assert sorted(_pending() - set(_entries())) == []

    @pytest.mark.parametrize(
        ("entry", "pending"),
        [
            pytest.param({}, False, id="neither key"),
            pytest.param({"tests": ["x"], "no_test": "human: y"}, False, id="both keys"),
            pytest.param({"no_test": "a model: y"}, False, id="unknown kind"),
            pytest.param({"no_test": "human:  "}, False, id="empty reason"),
            pytest.param({"tests": []}, False, id="empty list"),
            pytest.param({"tests": ["tests/nowhere.py::test_x"]}, False, id="no file"),
            pytest.param(
                {"tests": ["tests/test_scenario_traceability.py::test_x"]}, False, id="no function"
            ),
            pytest.param(
                {"tests": ["tests/test_scenario_traceability.py::TestX::test_x"]},
                False,
                id="no class",
            ),
            pytest.param(
                {"tests": ["tests/test_scenario_traceability.py::test_x[a]"]}, False, id="bracket"
            ),
            pytest.param(
                {
                    "fixture": "f",
                    "tests": [
                        "tests/test_scenario_traceability.py::TestEveryScenarioHasATestOrAReason"
                    ],
                },
                False,
                id="run unlisted",
            ),
            pytest.param({"no_test": "human: y"}, True, id="pending with a key"),
        ],
    )
    def test_the_check_names_a_scenario_that_breaks_a_rule(
        self, entry: Mapping[str, object], pending: bool
    ) -> None:
        assert _problems("uc-00-01", entry, {"uc-00-01"} if pending else set()) != []

    @pytest.mark.parametrize(
        ("entry", "pending"),
        [
            pytest.param({}, True, id="pending"),
            pytest.param({"no_test": "limit: Graph has no such call"}, False, id="a reason"),
            pytest.param(
                {
                    "tests": [
                        "tests/test_scenario_traceability.py::TestEveryScenarioHasATestOrAReason"
                    ]
                },
                False,
                id="a class",
            ),
            pytest.param(
                {
                    "tests": [
                        "tests/test_scenario_traceability.py::TestEveryScenarioHasATestOrAReason::test_the_check_names_a_scenario_that_breaks_a_rule"
                    ]
                },
                False,
                id="a parametrized method without its bracket",
            ),
            pytest.param(
                {"fixture": "f", "tests": [f"{_RUNNER}[uc-00-01]"]}, False, id="a run of the runner"
            ),
        ],
    )
    def test_the_check_accepts_a_scenario_that_keeps_the_rules(
        self, entry: Mapping[str, object], pending: bool
    ) -> None:
        assert _problems("uc-00-01", entry, {"uc-00-01"} if pending else set()) == []
