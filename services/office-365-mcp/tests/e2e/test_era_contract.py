import contextlib
import json
from datetime import UTC, datetime
from typing import cast

import pytest
import respx
import yaml
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    InputRequiredResult,
    InputResponse,
    TextContent,
)
from mcp.types import ElicitResult as CarriedAnswer

from tests.e2e.recording import stand_in
from tests.e2e.recording.record import persona_values, with_personas
from tests.e2e.test_scenarios import HERE, Replay, build_server, items, mapping, patch_obo, resolved
from tests.e2e.test_tool_cases import RUNNABLE, freeze_the_clock

_IDS = {
    "anna": "00000000-a6b4-4b6e-8a2b-9e1c3f1e88e1",
    "tom": "00000000-e469-40d3-8f5b-9a7c5dac541e",
}
_PERSONAS = persona_values(stand_in.UPNS, {}, synthetic=True) | {
    f"persona:{key}.id": one for key, one in _IDS.items()
}


def _written(replay: Replay) -> int:
    return sum(not call.startswith("GET ") for _, call in replay.calls)


def _changed(value: object) -> object | None:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return f"{value} changed"
    if isinstance(value, list) and value:
        return [*cast("list[object]", value), cast("list[object]", value)[-1]]
    return None


def _said(result: CallToolResult) -> str:
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))


@pytest.fixture(scope="module")
def server() -> FastMCP[None]:
    return build_server()


@pytest.mark.parametrize("case", RUNNABLE)
async def test_a_tool_that_asks_writes_only_under_the_answer_it_asked_for(
    case: str, server: FastMCP[None], monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = (HERE / "fixtures" / f"rec-tool-{case}.meta.yaml").read_text()
    meta = mapping(cast("object", yaml.safe_load(stored)))
    patch_obo(monkeypatch)
    freeze_the_clock(monkeypatch, datetime.fromisoformat(str(meta["recorded_at"])).astimezone(UTC))
    steps = [mapping(with_personas(step, _PERSONAS)) for step in items(RUNNABLE[case]["chain"])]
    recorded = cast("object", json.loads((HERE / "fixtures" / f"rec-tool-{case}.json").read_text()))
    replay = Replay([mapping(one) for one in items(recorded)])
    results: list[object] = []
    asked_tools: list[str] = []
    with respx.mock(assert_all_mocked=True) as graph:
        _ = graph.route().mock(side_effect=replay)
        async with Client(FastMCPTransport(server)) as client:
            for step in steps:
                tool = str(step.get("pick", step.get("tool")))
                given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
                arguments = {k: resolved(v, results) for k, v in given.items()}
                served = set(replay.served)
                first = await client.session.call_tool(tool, arguments, allow_input_required=True)
                if isinstance(first, CallToolResult):
                    assert not first.is_error or "tool_error" in mapping(step.get("expect", {}))
                    results.append(cast("object", first.structured_content))
                    continue
                assert isinstance(first, InputRequiredResult)
                asked_tools.append(tool)
                replay.reusable = replay.served - served
                ((key, asked),) = (first.input_requests or {}).items()
                form = cast("ElicitRequestFormParams", cast("ElicitRequest", asked).params)
                yes = cast("list[str]", form.requested_schema["properties"]["value"]["enum"])[0]
                accept: dict[str, InputResponse] = {
                    key: CarriedAnswer(action="accept", content={"value": yes})
                }
                no: dict[str, InputResponse] = {key: CarriedAnswer(action="decline")}
                before = _written(replay)
                declined = await client.session.call_tool(
                    tool,
                    arguments,
                    input_responses=no,
                    request_state=first.request_state,
                    allow_input_required=True,
                )
                assert isinstance(declined, CallToolResult)
                assert declined.is_error and "not confirmed" in _said(declined), _said(declined)
                stateless = await client.session.call_tool(
                    tool, arguments, input_responses=accept, allow_input_required=True
                )
                assert isinstance(stateless, CallToolResult)
                assert stateless.is_error and "different request" in _said(stateless)
                assert _written(replay) == before, f"{tool} wrote without a matching answer"
                for name, value in arguments.items():
                    other = _changed(value)
                    if other is None:
                        continue
                    mark = len(replay.unmatched)
                    with contextlib.suppress(MCPError):
                        _ = await client.session.call_tool(
                            tool,
                            {**arguments, name: other},
                            input_responses=accept,
                            request_state=first.request_state,
                            allow_input_required=True,
                        )
                    del replay.unmatched[mark:]
                    assert _written(replay) == before, f"{tool}: an answer covered a changed {name}"
                done = await client.session.call_tool(
                    tool,
                    arguments,
                    input_responses=accept,
                    request_state=first.request_state,
                    allow_input_required=True,
                )
                assert isinstance(done, CallToolResult)
                assert not done.is_error, _said(done)
                assert _written(replay) > before, f"{tool} wrote nothing for the agreed request"
                replay.reusable = set()
                results.append(cast("object", done.structured_content))
    assert not replay.unmatched, "\n".join(replay.unmatched)


_TOOLS = HERE.parents[1] / "src" / "office_365_mcp" / "tools"
_SCENARIO_14 = "tests/tools/scenarios/test_14_share_and_delegate_calendars.py"
_RUN_BY_A_SCENARIO = {
    "outlook_share_calendar": _SCENARIO_14,
    "outlook_unshare_calendar": _SCENARIO_14,
}


def test_every_tool_that_asks_is_run_by_a_case_or_by_a_named_scenario() -> None:
    asking = {path.stem for path in _TOOLS.glob("*.py") if "person_confirms" in path.read_text()}
    run = {
        str(mapping(step).get("pick", mapping(step).get("tool")))
        for entry in RUNNABLE.values()
        for step in items(entry["chain"])
    }
    assert asking - run == set(_RUN_BY_A_SCENARIO)
