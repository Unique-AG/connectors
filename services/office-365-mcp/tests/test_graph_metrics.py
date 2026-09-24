import ast
import asyncio
import json
import pathlib
import re
from collections.abc import AsyncGenerator, Iterator, Mapping, Sequence
from typing import TypeGuard, cast

import httpx
import pytest
import respx
from fastmcp import Context
from fastmcp.exceptions import ToolError
from kiota_http.middleware import retry_handler
from msgraph.generated.models.message import Message
from msgraph.graph_service_client import GraphServiceClient
from prometheus_client import generate_latest
from unique_toolkit.monitoring import REGISTRY

from office_365_mcp.config import AppConfig
from office_365_mcp.graph_client import (
    GRAPH_OPERATION_DURATION_SECONDS,
    GRAPH_OPERATIONS_TOTAL,
    GRAPH_PAGES_SCANNED,
    GRAPH_STATUSES,
    GRAPH_STEP_DURATION_SECONDS,
    GRAPH_STEPS_TOTAL,
    GRAPH_THROTTLED_TOTAL,
    GraphForbidden,
    GraphSettings,
    GraphThrottled,
    collect_pages,
    create_graph_transport,
    graph_client_for,
    graph_errors,
    graph_step,
)
from office_365_mcp.metrics import configure_metrics
from office_365_mcp.shared.handles import TranscriptHandle
from office_365_mcp.tools import teams_read_transcript as transcript_reader
from office_365_mcp.tools.outlook_send_draft import a_person_agrees, send_draft
from office_365_mcp.tools.teams_read_transcript import STEP_ATTRIBUTED, teams_read_transcript
from office_365_mcp.tools.teams_read_transcript import TOOL_NAME as TRANSCRIPT_TOOL

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

CALLER_TOKEN = "synthetic-graph-access-token"

_CHATS_PATH = "/me/chats"

_TRANSCRIPT_MEETING = "MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"
_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0002"
_TRANSCRIPT_PATH = f"/me/onlineMeetings/{_TRANSCRIPT_MEETING}/transcripts/{_TRANSCRIPT_ID}/content"
_ME = {"id": "00000000-0000-4000-8000-000000000001", "displayName": "Ada Lovelace"}


@pytest.fixture
def graph() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def transport() -> AsyncGenerator[httpx.AsyncClient]:
    client = create_graph_transport(GraphSettings())
    yield client
    await client.aclose()


@pytest.fixture
def client(transport: httpx.AsyncClient) -> GraphServiceClient:
    return graph_client_for(transport, CALLER_TOKEN)


@pytest.fixture(autouse=True)
def metrics_provider() -> None:
    _ = configure_metrics(
        AppConfig.model_validate({"public_base_url": "https://office-365-mcp.example"})
    )


@pytest.fixture
def no_retry_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Instant:
        async def sleep(self, _delay: float) -> None:
            return None

    monkeypatch.setattr(retry_handler, "asyncio", _Instant())


def _samples(metric: str) -> dict[frozenset[tuple[str, str]], float]:
    found: dict[frozenset[tuple[str, str]], float] = {}
    for line in generate_latest(REGISTRY).decode().splitlines():
        if line.startswith("#") or not line.startswith(metric):
            continue
        series, _, value = line.rpartition(" ")
        name, _, labels = series.partition("{")
        if name != metric:
            continue
        found[frozenset(_labels(labels.rstrip("}")))] = float(value)
    return found


def _labels(rendered: str) -> Iterator[tuple[str, str]]:
    for pair in rendered.split('",') if rendered else ():
        name, _, value = pair.partition("=")
        yield name.strip(), value.strip().strip('"')


def _value(metric: str, **labels: str) -> float:
    wanted = frozenset(labels.items())
    matched = [value for keys, value in _samples(metric).items() if wanted <= keys]
    assert len(matched) <= 1, f"{metric}{labels} matched {len(matched)} series"
    return matched[0] if matched else 0.0


def _boundaries(metric: str) -> set[str]:
    return {
        line.partition('le="')[2].partition('"')[0]
        for line in generate_latest(REGISTRY).decode().splitlines()
        if line.startswith(f"{metric}_bucket")
    }


async def _walk_chats(client: GraphServiceClient, *, limit: int) -> None:
    from msgraph.generated.models.chat_collection_response import ChatCollectionResponse

    first = await client.me.chats.get()
    assert isinstance(first, ChatCollectionResponse)
    _ = await collect_pages(first, client, limit=limit)


def _page(chat_ids: Sequence[str], next_link: str | None = None) -> Mapping[str, object]:
    page: dict[str, object] = {"value": [{"id": chat_id} for chat_id in chat_ids]}
    if next_link is not None:
        page["@odata.nextLink"] = next_link
    return page


class TestAGraphCallIsCountedAndTimed:
    async def test_a_call_shows_up_in_the_registry_the_metrics_route_scrapes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        before = _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="ok")
        timed = _value(f"{GRAPH_OPERATION_DURATION_SECONDS}_count", operation="get_me")

        with graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="ok") == before + 1
        assert _value(f"{GRAPH_OPERATION_DURATION_SECONDS}_count", operation="get_me") == timed + 1

    @pytest.mark.parametrize(
        "histogram",
        [GRAPH_OPERATION_DURATION_SECONDS, GRAPH_STEP_DURATION_SECONDS],
        ids=repr,
    )
    async def test_a_graph_latency_histogram_reaches_minutes_and_not_only_ten_seconds(
        self, client: GraphServiceClient, graph: respx.MockRouter, histogram: str
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        with graph_errors("get_me"), graph_step("signed_in_user"):
            _ = await client.me.get()

        boundaries = _boundaries(histogram)

        assert boundaries, f"{histogram} is absent from the scrape entirely"
        assert {"30.0", "60.0", "120.0", "300.0"} <= boundaries, (
            f"the minute buckets are missing from {histogram}, which has {sorted(boundaries)}"
        )

    async def test_a_refusal_is_counted_under_its_remedy_and_not_its_status_code(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(403, json={}))
        before = _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="forbidden")

        with pytest.raises(GraphForbidden), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="forbidden") == before + 1

    async def test_a_transcript_over_the_ceiling_is_counted_under_its_own_status(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(transcript_reader, "MAX_TRANSCRIPT_BYTES", 64)
        _ = graph.get(_TRANSCRIPT_PATH).mock(
            return_value=httpx.Response(
                200, content=b"x" * 65, headers={"Content-Type": "text/vtt"}
            )
        )
        before = _value(GRAPH_OPERATIONS_TOTAL, operation=TRANSCRIPT_TOOL, status="too_large")
        stepped = _value(
            GRAPH_STEPS_TOTAL, operation=TRANSCRIPT_TOOL, step=STEP_ATTRIBUTED, status="too_large"
        )

        with pytest.raises(ToolError):
            _ = await teams_read_transcript(
                client,
                transport,
                handle=TranscriptHandle(_TRANSCRIPT_MEETING, _TRANSCRIPT_ID),
                offset=0,
                limit=20,
            )

        assert (
            _value(GRAPH_OPERATIONS_TOTAL, operation=TRANSCRIPT_TOOL, status="too_large")
            == before + 1
        ), "the refusal was not counted as a size refusal, so the dashboard excludes nothing"
        assert (
            _value(
                GRAPH_STEPS_TOTAL,
                operation=TRANSCRIPT_TOOL,
                step=STEP_ATTRIBUTED,
                status="too_large",
            )
            == stepped + 1
        )

    async def test_a_person_declining_a_send_is_not_counted_as_a_graph_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        draft_id = "AAMkAGI2SYNTHETIC-immutable-0001%3D"
        _ = graph.get(f"/me/messages/{draft_id}").mock(
            return_value=httpx.Response(
                200, json={"id": draft_id, "isDraft": True, "subject": "Invoice 4471"}
            )
        )
        sent = graph.post(f"/me/messages/{draft_id}/send").mock(return_value=httpx.Response(202))
        before = _value(GRAPH_OPERATIONS_TOTAL, operation="outlook_send_draft", status="error")

        answered = _value(GRAPH_OPERATIONS_TOTAL, operation="outlook_send_draft", status="ok")

        async def declines(draft: Message, mailbox: str | None) -> str | None:
            assert draft is not None
            assert mailbox is None
            return "Nothing was sent."

        with pytest.raises(ToolError):
            _ = await send_draft(
                client, confirm=declines, draft_ref=f"outlook:///drafts/{draft_id}"
            )

        assert sent.call_count == 0, "a declined send reached the mailbox"
        assert (
            _value(GRAPH_OPERATIONS_TOTAL, operation="outlook_send_draft", status="error") == before
        ), "a person saying no was counted as a Graph failure"
        assert (
            _value(GRAPH_OPERATIONS_TOTAL, operation="outlook_send_draft", status="ok")
            == answered + 1
        ), "the read that did happen stopped being counted at all"

    async def test_a_client_that_cannot_ask_is_not_counted_as_a_graph_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:

        class _CannotAsk:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message and response_type is not None
                raise RuntimeError("elicitation not supported")

        draft_id = "AAMkAGI2SYNTHETIC-immutable-0002%3D"
        _ = graph.get(f"/me/messages/{draft_id}").mock(
            return_value=httpx.Response(
                200, json={"id": draft_id, "isDraft": True, "subject": "Invoice 4471"}
            )
        )
        sent = graph.post(f"/me/messages/{draft_id}/send").mock(return_value=httpx.Response(202))
        before = _value(GRAPH_OPERATIONS_TOTAL, operation="outlook_send_draft", status="error")

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await send_draft(
                client,
                confirm=a_person_agrees(cast("Context", cast("object", _CannotAsk()))),
                draft_ref=f"outlook:///drafts/{draft_id}",
            )

        assert sent.call_count == 0
        assert (
            _value(GRAPH_OPERATIONS_TOTAL, operation="outlook_send_draft", status="error") == before
        ), "a client that cannot ask was counted as a Graph failure"

    async def test_the_wait_for_a_person_is_not_timed_as_graph_latency(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        draft_id = "AAMkAGI2SYNTHETIC-immutable-0003%3D"
        _ = graph.get(f"/me/messages/{draft_id}").mock(
            return_value=httpx.Response(
                200, json={"id": draft_id, "isDraft": True, "subject": "Invoice 4471"}
            )
        )
        _ = graph.post(f"/me/messages/{draft_id}/send").mock(return_value=httpx.Response(202))
        waited = 0.5
        before = _value(f"{GRAPH_OPERATION_DURATION_SECONDS}_sum", operation="outlook_send_draft")

        async def thinks_about_it(draft: Message, mailbox: str | None) -> str | None:
            assert draft is not None
            assert mailbox is None
            await asyncio.sleep(waited)
            return None

        _ = await send_draft(
            client, confirm=thinks_about_it, draft_ref=f"outlook:///drafts/{draft_id}"
        )

        timed = (
            _value(f"{GRAPH_OPERATION_DURATION_SECONDS}_sum", operation="outlook_send_draft")
            - before
        )
        assert timed < waited / 2, f"the wait for a person was timed as Graph latency: {timed}s"

    async def test_a_step_with_no_operation_above_it_is_not_counted_under_a_made_up_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        before = _samples(GRAPH_OPERATIONS_TOTAL)
        steps = _samples(GRAPH_STEPS_TOTAL)

        with graph_step("signed_in_user"):
            _ = await client.me.get()

        assert _samples(GRAPH_OPERATIONS_TOTAL) == before
        assert _samples(GRAPH_STEPS_TOTAL) == steps


class TestOneGraphCallInsideAToolIsMeasuredOnItsOwn:
    async def test_a_step_is_counted_and_timed_under_the_operation_that_reached_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        counted = _value(GRAPH_STEPS_TOTAL, operation="get_me", step="signed_in_user", status="ok")
        timed = _value(
            f"{GRAPH_STEP_DURATION_SECONDS}_count", operation="get_me", step="signed_in_user"
        )

        with graph_errors("get_me"), graph_step("signed_in_user"):
            _ = await client.me.get()

        assert (
            _value(GRAPH_STEPS_TOTAL, operation="get_me", step="signed_in_user", status="ok")
            == counted + 1
        )
        assert (
            _value(
                f"{GRAPH_STEP_DURATION_SECONDS}_count", operation="get_me", step="signed_in_user"
            )
            == timed + 1
        )

    async def test_a_refused_step_a_tool_recovers_from_leaves_the_operation_counted_as_answered(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(
            side_effect=[httpx.Response(403, json={}), httpx.Response(200, json=_ME)]
        )
        answered = _value(GRAPH_OPERATIONS_TOTAL, operation="teams_read_transcript", status="ok")
        refused_operations = _value(
            GRAPH_OPERATIONS_TOTAL, operation="teams_read_transcript", status="forbidden"
        )
        refused_steps = _value(
            GRAPH_STEPS_TOTAL,
            operation="teams_read_transcript",
            step="transcript_attributed",
            status="forbidden",
        )

        with graph_errors("teams_read_transcript"):
            try:
                with graph_step("transcript_attributed"):
                    _ = await client.me.get()
            except GraphForbidden:
                with graph_step("transcript_unattributed"):
                    _ = await client.me.get()

        assert (
            _value(GRAPH_OPERATIONS_TOTAL, operation="teams_read_transcript", status="ok")
            == answered + 1
        )
        assert (
            _value(GRAPH_OPERATIONS_TOTAL, operation="teams_read_transcript", status="forbidden")
            == refused_operations
        ), "the tool answered, so the operation is not a refusal"
        assert (
            _value(
                GRAPH_STEPS_TOTAL,
                operation="teams_read_transcript",
                step="transcript_attributed",
                status="forbidden",
            )
            == refused_steps + 1
        ), "the refusal is real and belongs to the attempt that was refused"


class TestTheOperationLabelIsANameThisCodeChose:
    async def test_no_graph_series_carries_a_url_a_path_or_a_resource_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        chat_id = "19%3Aunbounded-cardinality%40thread.v2"
        _ = graph.get(f"/chats/{chat_id}").mock(return_value=httpx.Response(200, json={"id": "c"}))

        with graph_errors("teams_list_chats"):
            _ = await client.chats.by_chat_id("19:unbounded-cardinality@thread.v2").get()

        families = (
            GRAPH_OPERATIONS_TOTAL,
            f"{GRAPH_OPERATION_DURATION_SECONDS}_count",
            f"{GRAPH_PAGES_SCANNED}_count",
            GRAPH_THROTTLED_TOTAL,
        )
        values = {
            value
            for family in families
            for labels in _samples(family)
            for name, value in labels
            if name in ("operation", "status", "retried")
        }
        assert values, "no graph series was found at all, so this asserts over nothing"
        for value in values:
            assert "/" not in value, f"{value} looks like a path"
            assert "graph.microsoft.com" not in value
            assert "unbounded-cardinality" not in value


class TestThrottlingSaysWhetherTheSdkSpentItsRetries:
    @pytest.mark.usefixtures("no_retry_waiting")
    async def test_retries_spent_on_a_wait_the_sdk_was_willing_to_make(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
        before = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true") == before + 1

    @pytest.mark.usefixtures("no_retry_waiting")
    async def test_a_503_that_named_a_delay_is_counted_as_throttling_and_not_as_an_outage(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me").mock(return_value=httpx.Response(503, headers={"Retry-After": "7"}))
        throttled = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true")
        counted = _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="throttled")
        outages = _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="unavailable")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true") == throttled + 1
        assert _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="throttled") == counted + 1
        assert _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="unavailable") == outages

    @pytest.mark.usefixtures("no_retry_waiting")
    async def test_no_retry_attempted_when_graph_asked_for_a_wait_past_the_ceiling(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "600"}))
        before = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false") == before + 1


class TestAPagedWalkReportsWhatItRead:
    async def test_the_pages_a_walk_read_include_the_callers_own_first_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        second = f"{GRAPH_V1}/me/chats?$skiptoken=two"
        third = f"{GRAPH_V1}/me/chats?$skiptoken=three"
        graph.get(_CHATS_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_page(["c-1"], second)),
                httpx.Response(200, json=_page(["c-2"], third)),
                httpx.Response(200, json=_page(["c-3"])),
            ]
        )
        before = _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="teams_list_chats")

        with graph_errors("teams_list_chats"):
            await _walk_chats(client, limit=50)

        assert _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="teams_list_chats") == before + 3

    async def test_a_nested_unnamed_block_does_not_erase_the_name_in_scope(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_CHATS_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_page(["c-1"], f"{GRAPH_V1}/me/chats?$skiptoken=two")),
                httpx.Response(200, json=_page(["c-2"])),
            ]
        )
        pages = _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="teams_list_chats")
        counted = _value(GRAPH_OPERATIONS_TOTAL, operation="teams_list_chats", status="ok")

        steps = _value(GRAPH_STEPS_TOTAL, operation="teams_list_chats", step="chats", status="ok")

        with graph_errors("teams_list_chats"), graph_step("chats"):
            await _walk_chats(client, limit=50)

        assert _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="teams_list_chats") == pages + 2
        assert (
            _value(GRAPH_OPERATIONS_TOTAL, operation="teams_list_chats", status="ok") == counted + 1
        ), (
            "the inner block is a step, so it counts against the step instruments and leaves the "
            + "operation counted once — otherwise a tool that names its calls would look like a "
            + "tool called several times"
        )
        assert (
            _value(GRAPH_STEPS_TOTAL, operation="teams_list_chats", step="chats", status="ok")
            == steps + 1
        )


_SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "office_365_mcp"
_TOOLS = _SOURCE_ROOT / "tools"


def _tool_sources() -> list[pathlib.Path]:
    return sorted(path for path in _TOOLS.glob("*.py") if path.name != "__init__.py")


def _source_modules() -> list[pathlib.Path]:
    return sorted(_SOURCE_ROOT.rglob("*.py"))


def _source_id(source: pathlib.Path) -> str:
    return source.relative_to(_SOURCE_ROOT).as_posix()


def _parsed(source: pathlib.Path) -> ast.Module:
    return ast.parse(source.read_text())


def _graph_errors_calls(module: ast.Module) -> list[ast.Call]:
    return [node for node in ast.walk(module) if _is_graph_errors(node)]


def _is_graph_errors(node: ast.AST) -> TypeGuard[ast.Call]:
    return _calls(node, "graph_errors")


def _graph_step_calls(module: ast.Module) -> list[ast.Call]:
    return [node for node in ast.walk(module) if _is_graph_step(node)]


def _is_graph_step(node: ast.AST) -> TypeGuard[ast.Call]:
    return _calls(node, "graph_step")


def _calls(node: ast.AST, name: str) -> TypeGuard[ast.Call]:
    if not isinstance(node, ast.Call):
        return False
    called = node.func
    if isinstance(called, ast.Name):
        return called.id == name
    return isinstance(called, ast.Attribute) and called.attr == name


class TestEveryToolNamesItselfWhenItCallsGraph:
    def test_the_tools_are_actually_there(self) -> None:
        sources = _tool_sources()
        assert len(sources) > 1, f"no tool modules found under {_TOOLS}"
        assert any(_graph_errors_calls(_parsed(source)) for source in sources)

    @pytest.mark.parametrize("source", _tool_sources(), ids=_source_id)
    def test_every_graph_call_is_named_after_the_tool_that_makes_it(
        self, source: pathlib.Path
    ) -> None:
        unnamed = [
            call.lineno
            for call in _graph_errors_calls(_parsed(source))
            if [argument for argument in call.args if _names_the_tool(argument)] == []
            and [keyword for keyword in call.keywords if _names_the_tool(keyword.value)] == []
        ]
        assert not unnamed, (
            f"{source.name} calls graph_errors without its own TOOL_NAME at line(s) "
            + f"{unnamed}. Every Graph call a tool makes is counted under `operation`, and a call "
            + "that names nothing is counted nowhere — the tool goes missing from "
            + f"{GRAPH_OPERATIONS_TOTAL} rather than showing up under a wrong name."
        )


def _names_the_tool(argument: ast.expr) -> bool:
    return isinstance(argument, ast.Name) and argument.id == "TOOL_NAME"


class TestNoOperationNameIsTakenFromData:
    def test_the_rule_reaches_past_the_tools_directory(self) -> None:
        modules = _source_modules()
        assert len(modules) > len(_tool_sources()), f"no modules found under {_SOURCE_ROOT}"
        calling = {
            _source_id(module)
            for module in modules
            if _graph_errors_calls(_parsed(module)) or _graph_step_calls(_parsed(module))
        }
        assert calling - {_source_id(source) for source in _tool_sources()}, (
            "every measured Graph call is under tools/, so this asserts nothing the tools-only "
            + "rule did not — find the caller that moved before narrowing the glob back"
        )

    @pytest.mark.parametrize("source", _source_modules(), ids=_source_id)
    def test_the_operation_is_a_name_this_code_chose(self, source: pathlib.Path) -> None:
        module = _parsed(source)
        chosen = frozenset(_module_level_strings(module))
        derived = [
            (call.lineno, ast.unparse(named))
            for call in _graph_errors_calls(module)
            if (named := _operation_named(call)) is not None
            and not _is_chosen_in_code(named, chosen)
        ]
        assert not derived, (
            f"{_source_id(source)} passes graph_errors an operation it did not choose in code, at "
            + f"(line, expression) {derived}. `operation` is a Prometheus label: a URL, a path, or "
            + "anything read off an argument is a new time series per chat, per message and per "
            + f"meeting, and an unbounded label set on {GRAPH_OPERATIONS_TOTAL} takes the "
            + "Prometheus down rather than showing up as a bad dashboard. Pass a constant this "
            + "module binds "
            + "at its top level, the way every tool passes its own TOOL_NAME."
        )


def _operation_named(call: ast.Call) -> ast.expr | None:
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "operation":
            return keyword.value
        if keyword.arg is None:
            return keyword.value
    return None


def _module_level_strings(module: ast.Module) -> dict[str, str]:
    return {
        target.id: value
        for statement in module.body
        for target, value in _assigned_names(statement)
        if isinstance(target, ast.Name)
    }


def _assigned_names(statement: ast.stmt) -> list[tuple[ast.expr, str]]:
    if isinstance(statement, ast.Assign) and _is_string(statement.value):
        return [(target, _string_of(statement.value)) for target in statement.targets]
    if (
        isinstance(statement, ast.AnnAssign)
        and statement.value is not None
        and _is_string(statement.value)
    ):
        return [(statement.target, _string_of(statement.value))]
    return []


def _string_of(node: ast.expr) -> str:
    assert isinstance(node, ast.Constant) and isinstance(node.value, str), (
        f"only reached for a node _is_string accepted, got {ast.dump(node)}"
    )
    return node.value


def _is_string(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_chosen_in_code(named: ast.expr, chosen: frozenset[str]) -> bool:
    if _is_string(named):
        return True
    return isinstance(named, ast.Name) and named.id in chosen


GRAPH_STEPS = frozenset(
    {
        "signed_in_user",
        "file_search",
        "my_drive",
        "folder_children",
        "drive_item",
        "drive_content",
        "chats",
        "joined_teams",
        "channels",
        "channel_messages",
        "chat_message",
        "channel_message",
        "channel_reply",
        "search_query",
        "resolve_meeting",
        "transcripts",
        "recordings",
        "mail_search",
        "mail_ids",
        "mail_message",
        "mail_folders",
        "people_search",
        "mail_participants",
        "thread_anchor",
        "thread_messages",
        "mail_folder",
        "folder_messages",
        "mailbox_settings",
        "mail_rules",
        "mail_categories",
        "categories",
        "mark_message",
        "move_message",
        "destination_folder",
        "create_draft",
        "create_reply",
        "fill_reply",
        "attach_inline",
        "create_upload_session",
        "upload_session_chunks",
        "read_draft",
        "send_draft",
        "read_mailbox_settings",
        "write_automatic_reply",
        "read_mail_rule",
        "disable_mail_rule",
        "transcript_attributed",
        "transcript_unattributed",
        "calendar",
        "calendars",
        "calendar_events",
        "calendar_event",
        "create_event",
        "update_event",
        "cancel_event",
        "respond_to_invite",
        "get_schedule",
        "find_meeting_times",
        "notebook",
        "notebooks",
        "section",
        "sections",
        "section_groups",
        "section_group",
        "pages",
        "page",
        "page_content",
        "create_page",
        "append_content",
        "preview",
        "resource_content",
        "notebook_from_url",
        "recent_notebooks",
        "create_notebook",
        "create_section",
        "create_section_group",
        "edit_content",
        "rename_page",
        "delete_page",
        "copy_page",
        "copy_section",
        "copy_notebook",
        "operation",
    }
)

_STEP_CONSTANT = re.compile(r"^STEP(_[A-Z0-9_]+)?$")

_STEP_VALUE = re.compile(r"^[a-z][a-z0-9_]*$")


def _declared_steps() -> dict[str, str]:
    found: dict[str, str] = {}
    for source in _source_modules():
        module = _parsed(source)
        constants = _module_level_strings(module)
        for call in (*_graph_errors_calls(module), *_graph_step_calls(module)):
            step = _step_named(call)
            if step is None:
                continue
            if _is_string(step):
                found[f"{_source_id(source)}:{call.lineno}"] = _string_of(step)
            elif isinstance(step, ast.Name) and step.id in constants:
                found[f"{_source_id(source)}:{call.lineno}"] = constants[step.id]
    return found


class TestNoStepNameIsTakenFromData:
    def test_there_are_steps_to_read(self) -> None:
        declared = _declared_steps()
        assert len(declared) > 1, f"no STEP constants found under {_SOURCE_ROOT}"
        outside_tools = {
            qualified for qualified in declared if not qualified.startswith(f"{_TOOLS.name}/")
        }
        assert outside_tools, (
            "every step is declared under tools/, so the modules that own a shared Graph call "
            + "(shared/identity.py, shared/meetings.py) have stopped naming their own — find where "
            + "their step went before assuming this rule still covers them"
        )

    @pytest.mark.parametrize("source", _source_modules(), ids=_source_id)
    def test_the_step_is_a_name_this_code_chose(self, source: pathlib.Path) -> None:
        module = _parsed(source)
        chosen = frozenset(_module_level_strings(module))
        named = [
            (call.lineno, step)
            for call in (*_graph_errors_calls(module), *_graph_step_calls(module))
            if (step := _step_named(call)) is not None
        ]
        derived = [
            (lineno, ast.unparse(step))
            for lineno, step in named
            if not _is_chosen_in_code(step, chosen)
        ]
        assert not derived, (
            f"{_source_id(source)} passes a step it did not choose in code, at (line, expression) "
            + f"{derived}. `step` is a Prometheus label and it multiplies against `operation`: a "
            + "value read off an argument is a new time series per chat, per message and per "
            + f"meeting on {GRAPH_STEPS_TOTAL} and {GRAPH_STEP_DURATION_SECONDS} both. Bind a "
            + "STEP constant at the module's top level, the way every tool binds its own."
        )

    def test_the_step_vocabulary_is_the_one_this_service_signed_off_on(self) -> None:
        assert set(_declared_steps().values()) == GRAPH_STEPS, (
            "the STEP constants under src/ no longer match GRAPH_STEPS above. This test is the "
            + "budget: each new step multiplies against the operation that reaches it on "
            + f"{GRAPH_STEPS_TOTAL} and {GRAPH_STEP_DURATION_SECONDS}. Adding one here is the "
            + "deliberate act that records it — a ceiling would have absorbed it silently."
        )

    def test_every_step_is_shaped_like_a_name_and_not_like_an_id(self) -> None:
        misshapen = {
            qualified: value
            for qualified, value in _declared_steps().items()
            if not _STEP_VALUE.match(value)
        }
        assert not misshapen, (
            f"step values must be lowercase identifiers, and {misshapen} are not. A step that "
            + "looks like a URL, a path or an id is one that was derived from data and then "
            + "written down as a constant, which passes every other rule here."
        )

    @pytest.mark.parametrize("source", _source_modules(), ids=_source_id)
    def test_a_step_constant_is_named_for_what_it_is(self, source: pathlib.Path) -> None:
        module = _parsed(source)
        constants = _module_level_strings(module)
        steps = {
            step.id
            for call in (*_graph_errors_calls(module), *_graph_step_calls(module))
            if isinstance(step := _step_named(call), ast.Name) and step.id in constants
        }
        assert not (odd := {name for name in steps if not _STEP_CONSTANT.match(name)}), (
            f"{_source_id(source)} passes its step as {sorted(odd)}. Name a step constant `STEP`, "
            + "or `STEP_<NAME>` where a module declares several, so `grep '^STEP' src/` answers "
            + "what this service can emit."
        )


def _step_named(call: ast.Call) -> ast.expr | None:
    if _is_graph_step(call) and call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "step":
            return keyword.value
        if keyword.arg is None:
            return keyword.value
    return None


_DASHBOARD = (
    pathlib.Path(__file__).resolve().parents[1]
    / "deploy"
    / "helm-charts"
    / "office-365-mcp"
    / "files"
    / "grafana-dashboard.json"
)

_GRAPH_METRIC_IN_A_QUERY = re.compile(r"\bgraph_[a-z_]+\b")
_PROMETHEUS_SUFFIXES = ("_bucket", "_count", "_sum")


def _panels() -> list[Mapping[str, object]]:
    dashboard = cast("Mapping[str, object]", json.loads(_DASHBOARD.read_text()))
    panels = dashboard.get("panels")
    assert isinstance(panels, list), f"the dashboard has no panel list, got {type(panels)}"
    return [panel for panel in cast("list[object]", panels) if isinstance(panel, Mapping)]


def _queries(panel: Mapping[str, object]) -> list[str]:
    targets = panel.get("targets")
    if not isinstance(targets, list):
        return []
    return [
        expression
        for target in cast("list[object]", targets)
        if isinstance(target, Mapping) and isinstance(expression := target.get("expr"), str)  # pyright: ignore[reportUnknownMemberType]
    ]


def _queried_graph_metrics() -> set[str]:
    return {
        _instrument(name)
        for panel in _panels()
        for query in _queries(panel)
        for name in _metric_names(query)
    }


def _metric_names(query: str) -> list[str]:
    return cast("list[str]", _GRAPH_METRIC_IN_A_QUERY.findall(query))


class TestTheDashboardAsksForMetricsThisServiceEmits:
    def test_the_dashboard_is_readable_json(self) -> None:
        assert _DASHBOARD.exists(), f"no dashboard at {_DASHBOARD}"
        assert len(_panels()) > 1, "a dashboard with no panels asserts nothing below"
        assert _queried_graph_metrics(), "no panel queries a graph_* series at all"

    def test_every_graph_series_a_panel_queries_is_one_the_code_declares(self) -> None:
        exported = {
            GRAPH_OPERATIONS_TOTAL,
            GRAPH_OPERATION_DURATION_SECONDS,
            GRAPH_THROTTLED_TOTAL,
            GRAPH_PAGES_SCANNED,
            GRAPH_STEPS_TOTAL,
            GRAPH_STEP_DURATION_SECONDS,
        }
        queried = _queried_graph_metrics()
        assert queried <= exported, (
            f"the dashboard queries {sorted(queried - exported)}, which "
            + "graph_client/observability.py does not declare. A panel asking for a series nobody "
            + "exports renders empty rather than failing, so a rename that misses a panel looks "
            + "exactly like a service with no traffic."
        )

    def test_every_graph_series_the_code_declares_is_on_a_panel(self) -> None:
        queried = _queried_graph_metrics()
        unplotted = {
            GRAPH_OPERATIONS_TOTAL,
            GRAPH_OPERATION_DURATION_SECONDS,
            GRAPH_THROTTLED_TOTAL,
            GRAPH_PAGES_SCANNED,
            GRAPH_STEPS_TOTAL,
            GRAPH_STEP_DURATION_SECONDS,
        } - queried
        assert not unplotted, (
            f"{sorted(unplotted)} is recorded on every call and shown to nobody. Either add the "
            + "panel or stop paying for the series."
        )


def _instrument(sample: str) -> str:
    for suffix in _PROMETHEUS_SUFFIXES:
        if sample.endswith(suffix):
            return sample[: -len(suffix)]
    return sample


_A_CALL_IN_A_TITLE = re.compile(r"\bcalls?\b", re.IGNORECASE)

_STEP_LEVEL = frozenset({GRAPH_STEPS_TOTAL, GRAPH_STEP_DURATION_SECONDS})


def _panel_graph_metrics(panel: Mapping[str, object]) -> set[str]:
    return {_instrument(name) for query in _queries(panel) for name in _metric_names(query)}


class TestNoPanelPromisesGraphCallsAndPlotsOperations:
    def test_a_panel_whose_title_says_call_plots_a_step_series(self) -> None:
        mislabelled = sorted(
            (title, tuple(sorted(queried)))
            for panel in _panels()
            if (queried := _panel_graph_metrics(panel))
            and isinstance(title := panel.get("title"), str)
            and _A_CALL_IN_A_TITLE.search(title)
            and not queried & _STEP_LEVEL
        )
        assert not mislabelled, (
            f"{mislabelled} says 'call' over a series that counts operations. An operation is one "
            + "tool call and a tool makes several Graph calls, so the panel reads as a Graph call "
            + f"rate and is not one. Title it an operation, or query {sorted(_STEP_LEVEL)}."
        )

    def test_a_step_series_is_plotted_under_that_name_somewhere(self) -> None:
        titled = {
            title
            for panel in _panels()
            if _panel_graph_metrics(panel) & _STEP_LEVEL
            and isinstance(title := panel.get("title"), str)
            and _A_CALL_IN_A_TITLE.search(title)
        }
        assert titled, (
            "no panel plots a step series under a title that says 'call'. Renaming the operation "
            + "panels leaves an operator with no Graph call rate at all, which is the confusion "
            + "the other way round."
        )


_EXCLUDED_STATUSES = re.compile(r'status!~\\?"([a-z_|]+)\\?"')


class TestTheDashboardDecidesAboutEveryStatusTheCodeCanEmit:
    def test_every_error_query_excludes_the_statuses_that_are_not_failures(self) -> None:
        not_failures = {"ok", "not_found", "cancelled", "too_large"}
        assert not_failures <= GRAPH_STATUSES, "this test names a status errors.py cannot emit"
        counted_as_failures = {
            (panel.get("title"), query)
            for panel in _panels()
            for query in _queries(panel)
            if "graph_" in query
            and (excluded := _EXCLUDED_STATUSES.search(query)) is not None
            and not not_failures <= set(excluded.group(1).split("|"))
        }
        assert not counted_as_failures, (
            f"{sorted(counted_as_failures)} counts a non-failure status as a failure. `cancelled` "
            + "is a caller that hung up and `not_found` is an answer, so a panel that filters "
            + '`status!~"ok"` alone reports both as this connector breaking.'
        )

    def test_no_query_names_a_status_the_code_cannot_emit(self) -> None:
        named = {
            status
            for panel in _panels()
            for query in _queries(panel)
            if "graph_" in query and (found := _EXCLUDED_STATUSES.search(query)) is not None
            for status in found.group(1).split("|")
        }
        assert named <= GRAPH_STATUSES, (
            f"the dashboard excludes {sorted(named - GRAPH_STATUSES)}, which errors.py never "
            + "records. An exclusion that matches nothing reads exactly like one that works."
        )
