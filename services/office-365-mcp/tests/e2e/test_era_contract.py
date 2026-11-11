import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import cast

import pytest
import respx
import yaml
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from mcp.server.request_state import RequestStateBoundary
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
    "mia": "00000000-aa0f-4286-8305-d989485e14b5",
    "anna": "00000000-a6b4-4b6e-8a2b-9e1c3f1e88e1",
    "tom": "00000000-e469-40d3-8f5b-9a7c5dac541e",
}
_PERSONAS = persona_values(stand_in.UPNS, {}, synthetic=True) | {
    f"persona:{key}.id": one for key, one in _IDS.items()
}
_TOOLS = HERE.parents[1] / "src" / "office_365_mcp" / "tools"
_SCENARIO_14 = "tests/tools/scenarios/test_14_share_and_delegate_calendars.py"
_SCENARIO_04 = "tests/tools/scenarios/test_04_draft_and_send_mail.py"
_SURFACE = "tests/tools/test_outlook_{}_surface.py"
_NEVER_ASKS_IN_A_CASE = {
    "outlook_share_calendar": _SCENARIO_14,
    "outlook_unshare_calendar": _SCENARIO_14,
    "outlook_draft_mail": _SURFACE.format("draft"),
    "outlook_draft_reply": _SURFACE.format("draft"),
    "outlook_mark_mail": _SURFACE.format("mark_and_move_mail"),
    "outlook_move_mail": _SURFACE.format("mark_and_move_mail"),
    "outlook_draft_reply_all": _SCENARIO_04,
    "outlook_update_draft": _SCENARIO_04,
    **{
        tool: f"tests/tools/test_{tool}.py"
        for tool in (
            "onenote_append_to_page",
            "onenote_copy_page",
            "onenote_copy_section",
            "onenote_create_notebook",
            "onenote_create_section",
            "onenote_create_section_group",
            "onenote_rename_page",
            "outlook_copy_mail",
            "outlook_create_folder",
            "outlook_rename_folder",
            "outlook_update_mail_rule",
            "sharepoint_create_list_item",
            "sharepoint_update_list_item",
            "sharepoint_delete_list_item",
        )
    },
}
_ASKING = {path.stem for path in _TOOLS.glob("*.py") if "person_confirms" in path.read_text()}


async def _unsealed(
    _self: RequestStateBoundary, ctx: object, call_next: Callable[[object], Awaitable[object]]
) -> object:
    return await call_next(ctx)


def _written(replay: Replay) -> int:
    return sum(not call.startswith("GET ") for _, call in replay.calls)


def _changed(value: object) -> object | None:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int | float):
        return value + 1
    if isinstance(value, str):
        return f"{value} changed"
    if isinstance(value, list) and value:
        last = _changed(cast("list[object]", value)[-1])
        return [*cast("list[object]", value)[:-1], last] if last is not None else None
    if isinstance(value, dict) and value:
        found = cast("dict[str, object]", value)
        for key, one in found.items():
            if (other := _changed(one)) is not None:
                return {**found, key: other}
    return None


def _said(result: CallToolResult) -> str:
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))


async def _tried(
    client: Client[FastMCPTransport],
    tool: str,
    arguments: dict[str, object],
    answer: dict[str, InputResponse],
    state: str | None,
) -> str | None:
    try:
        result = await client.session.call_tool(
            tool, arguments, input_responses=answer, request_state=state, allow_input_required=True
        )
    except MCPError as sealed:
        return "sealed" if "requestState" in str(sealed) else "other"
    if isinstance(result, CallToolResult) and result.is_error:
        return "digest" if "different request" in _said(result) else "other"
    return None


@pytest.fixture(scope="module")
def server() -> FastMCP[None]:
    return build_server()


async def _contract(
    client: Client[FastMCPTransport],
    replay: Replay,
    tool: str,
    arguments: dict[str, object],
    first: InputRequiredResult,
    sealed: bool,
) -> CallToolResult:
    ((key, asked),) = (first.input_requests or {}).items()
    form = cast("ElicitRequestFormParams", cast("ElicitRequest", asked).params)
    yes = cast("list[str]", form.requested_schema["properties"]["value"]["enum"])[0]
    accept: dict[str, InputResponse] = {key: CarriedAnswer(action="accept", content={"value": yes})}
    no: dict[str, InputResponse] = {key: CarriedAnswer(action="decline")}
    before = _written(replay)
    declined = await _tried(client, tool, arguments, no, first.request_state)
    assert declined == "other", f"{tool}: a decline was {declined}"
    assert await _tried(client, tool, arguments, accept, None) in {"digest", "sealed"}
    refusals: list[str | None] = []
    for name, value in arguments.items():
        if (other := _changed(value)) is None:
            continue
        mark = len(replay.unmatched)
        refusals.append(
            await _tried(client, tool, {**arguments, name: other}, accept, first.request_state)
        )
        del replay.unmatched[mark:]
        assert _written(replay) == before, f"{tool}: an answer covered a changed {name}"
    assert None not in refusals, f"{tool}: a changed argument was not refused: {refusals}"
    assert not sealed or set(refusals) <= {"sealed"}, f"{tool}: refused for another reason"
    assert _written(replay) == before, f"{tool} wrote without a matching answer"
    return await _agreed(client, tool, arguments, accept, first)


async def _agreed(
    client: Client[FastMCPTransport],
    tool: str,
    arguments: dict[str, object],
    accept: dict[str, InputResponse],
    first: InputRequiredResult,
) -> CallToolResult:
    done = await client.session.call_tool(
        tool,
        arguments,
        input_responses=accept,
        request_state=first.request_state,
        allow_input_required=True,
    )
    assert isinstance(done, CallToolResult)
    assert not done.is_error, _said(done)
    return done


async def _walk(
    case: str,
    server: FastMCP[None],
    monkeypatch: pytest.MonkeyPatch,
    *,
    sealed: bool,
    contract: bool,
) -> set[str]:
    stored = (HERE / "fixtures" / f"rec-tool-{case}.meta.yaml").read_text()
    meta = mapping(cast("object", yaml.safe_load(stored)))
    patch_obo(monkeypatch)
    freeze_the_clock(monkeypatch, datetime.fromisoformat(str(meta["recorded_at"])).astimezone(UTC))
    if not sealed:
        monkeypatch.setattr(RequestStateBoundary, "__call__", _unsealed)
    steps = [mapping(with_personas(step, _PERSONAS)) for step in items(RUNNABLE[case]["chain"])]
    recorded = cast("object", json.loads((HERE / "fixtures" / f"rec-tool-{case}.json").read_text()))
    replay = Replay([mapping(one) for one in items(recorded)])
    results: list[object] = []
    asked: set[str] = set()
    with respx.mock(assert_all_mocked=True) as graph:
        _ = graph.route().mock(side_effect=replay)
        async with Client(FastMCPTransport(server)) as client:
            for step in steps:
                tool = str(step.get("pick", step.get("tool")))
                given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
                arguments = {k: resolved(v, results) for k, v in given.items()}
                served = set(replay.served)
                before = _written(replay)
                first = await client.session.call_tool(tool, arguments, allow_input_required=True)
                if isinstance(first, CallToolResult):
                    assert first.is_error == ("tool_error" in mapping(step.get("expect", {})))
                    results.append(cast("object", first.structured_content))
                    continue
                assert isinstance(first, InputRequiredResult)
                assert _written(replay) == before, f"{tool} wrote before anybody agreed"
                asked.add(tool)
                replay.reusable = replay.served - served
                if contract:
                    done = await _contract(client, replay, tool, arguments, first, sealed)
                else:
                    ((key, form),) = (first.input_requests or {}).items()
                    options = cast("ElicitRequestFormParams", cast("ElicitRequest", form).params)
                    yes = cast("list[str]", options.requested_schema["properties"]["value"]["enum"])
                    done = await _agreed(
                        client,
                        tool,
                        arguments,
                        {key: CarriedAnswer(action="accept", content={"value": yes[0]})},
                        first,
                    )
                assert _written(replay) > before, f"{tool} wrote nothing for the agreed request"
                replay.reusable = set()
                results.append(cast("object", done.structured_content))
    assert not replay.unmatched, "\n".join(replay.unmatched)
    return asked


@pytest.mark.parametrize("sealed", [True, False], ids=["sealed", "digest-only"])
@pytest.mark.parametrize("case", RUNNABLE)
async def test_a_tool_that_asks_writes_only_under_the_answer_it_asked_for(
    case: str, sealed: bool, server: FastMCP[None], monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = await _walk(case, server, monkeypatch, sealed=sealed, contract=True)


async def test_every_tool_that_asks_is_asked_in_a_case_or_tested_where_it_is_named(
    server: FastMCP[None],
) -> None:
    needed = _ASKING - set(_NEVER_ASKS_IN_A_CASE)
    asked: set[str] = set()
    for case, entry in RUNNABLE.items():
        chain = {
            str(mapping(step).get("pick", mapping(step).get("tool")))
            for step in items(entry["chain"])
        }
        if not chain & (needed - asked):
            continue
        with pytest.MonkeyPatch.context() as patch:
            asked |= await _walk(case, server, patch, sealed=True, contract=False)
    assert needed <= asked, f"no recorded case asks through {sorted(needed - asked)}"
    assert set(_NEVER_ASKS_IN_A_CASE) <= _ASKING
    for tool, where in _NEVER_ASKS_IN_A_CASE.items():
        assert tool in (HERE.parents[1] / where).read_text(), f"{where} does not name {tool}"
