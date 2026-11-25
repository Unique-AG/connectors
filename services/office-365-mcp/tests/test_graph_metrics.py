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
from fastmcp import Client, Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_http.middleware import retry_handler
from mcp.shared.exceptions import MCPError
from mcp.types import (
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    InputRequiredResult,
)
from msgraph.generated.models.message import Message
from msgraph.graph_service_client import GraphServiceClient
from prometheus_client import generate_latest
from unique_toolkit.monitoring import REGISTRY

from office_365_mcp.cardinality import UNRESOLVED_NAME, BoundedNameMiddleware
from office_365_mcp.config import AppConfig
from office_365_mcp.graph_client import (
    GRAPH_OPERATION_DURATION_SECONDS,
    GRAPH_OPERATIONS_TOTAL,
    GRAPH_PAGES_SCANNED,
    GRAPH_SLOW_OPERATIONS_TOTAL,
    GRAPH_STATUSES,
    GRAPH_STEP_DURATION_SECONDS,
    GRAPH_STEPS_TOTAL,
    GRAPH_THROTTLED_TOTAL,
    GRAPH_TOKEN_ACQUISITIONS_TOTAL,
    GraphForbidden,
    GraphSettings,
    GraphThrottled,
    collect_pages,
    create_graph_transport,
    graph_client_for,
    graph_errors,
    graph_step,
    measured_graph_operation,
    no_retry,
    start_operation_series,
)
from office_365_mcp.graph_client.observability import record_graph_call
from office_365_mcp.graph_operations import (
    TOOL_OUTCOMES_TOTAL,
    GraphOperationMiddleware,
    is_refusal,
    start_tool_outcomes,
)
from office_365_mcp.metrics import configure_metrics
from office_365_mcp.shared.handles import TranscriptHandle
from office_365_mcp.shared.seam import Confirmed, GraphToken, TokenExchangeFailed, caller
from office_365_mcp.shared.teams import transcripts
from office_365_mcp.shared.teams.transcripts import STEP_ATTRIBUTED
from office_365_mcp.tools import get_me
from office_365_mcp.tools.get_me import SignedInUser
from office_365_mcp.tools.outlook_send_draft import a_person_agrees, send_draft
from office_365_mcp.tools.teams_list_call_transcripts import (
    STEP_TRANSCRIPTS as STEP_CALL_TRANSCRIPTS,
)
from office_365_mcp.tools.teams_list_call_transcripts import TOOL_NAME as CALL_TRANSCRIPTS_TOOL
from office_365_mcp.tools.teams_list_call_transcripts import teams_list_call_transcripts
from office_365_mcp.tools.teams_read_transcript import TOOL_NAME as TRANSCRIPT_TOOL
from office_365_mcp.tools.teams_read_transcript import teams_read_transcript
from office_365_mcp.tools.teams_send_channel_message import STEP_SEND as STEP_CHANNEL_SEND
from office_365_mcp.tools.teams_send_channel_message import TOOL_NAME as CHANNEL_SEND_TOOL
from office_365_mcp.tools.teams_send_channel_message import send_channel_message
from office_365_mcp.tools.teams_send_chat_message import STEP_SEND as STEP_CHAT_SEND
from office_365_mcp.tools.teams_send_chat_message import TOOL_NAME as CHAT_SEND_TOOL
from office_365_mcp.tools.teams_send_chat_message import send_chat_message

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


def _moves(
    metric: str, before: dict[frozenset[tuple[str, str]], float], label: str
) -> list[tuple[str, str, float]]:
    return [
        (dict(labels)["operation"], dict(labels)[label], value - before.get(labels, 0.0))
        for labels, value in _samples(metric).items()
        if value != before.get(labels, 0.0)
    ]


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


def _a_draft(draft_id: str) -> Mapping[str, object]:
    return {
        "id": draft_id,
        "isDraft": True,
        "subject": "Invoice 4471",
        "changeKey": "CQAAABYAAAC4SYNTHETIC-version-0001",
    }


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

        with measured_graph_operation("get_me"), graph_errors():
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

        with measured_graph_operation("get_me"), graph_errors(), graph_step("signed_in_user"):
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

        with pytest.raises(GraphForbidden), measured_graph_operation("get_me"), graph_errors():
            _ = await client.me.get()

        assert _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="forbidden") == before + 1

    async def test_a_transcript_over_the_ceiling_is_counted_under_its_own_status(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(transcripts, "MAX_TRANSCRIPT_BYTES", 64)
        _ = graph.get(_TRANSCRIPT_PATH).mock(
            return_value=httpx.Response(
                200, content=b"x" * 65, headers={"Content-Type": "text/vtt"}
            )
        )
        before = _value(GRAPH_OPERATIONS_TOTAL, operation=TRANSCRIPT_TOOL, status="too_large")
        stepped = _value(
            GRAPH_STEPS_TOTAL, operation=TRANSCRIPT_TOOL, step=STEP_ATTRIBUTED, status="too_large"
        )

        with (
            pytest.raises(ToolError),
            measured_graph_operation(TRANSCRIPT_TOOL, is_refusal=is_refusal),
        ):
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
            return_value=httpx.Response(200, json=_a_draft(draft_id))
        )
        sent = graph.post(f"/me/messages/{draft_id}/send").mock(return_value=httpx.Response(202))
        before = _value(GRAPH_OPERATIONS_TOTAL, operation="outlook_send_draft", status="error")

        answered = _value(GRAPH_OPERATIONS_TOTAL, operation="outlook_send_draft", status="ok")

        async def declines(draft: Message, mailbox: str | None) -> str | None:
            assert draft is not None
            assert mailbox is None
            return "Nothing was sent."

        with (
            pytest.raises(ToolError),
            measured_graph_operation("outlook_send_draft", is_refusal=is_refusal),
        ):
            _ = await send_draft(
                client, confirm=declines, message_ref=f"outlook:///messages/{draft_id}"
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
                raise MCPError(METHOD_NOT_FOUND, "Method not found")

        draft_id = "AAMkAGI2SYNTHETIC-immutable-0002%3D"
        _ = graph.get(f"/me/messages/{draft_id}").mock(
            return_value=httpx.Response(200, json=_a_draft(draft_id))
        )
        sent = graph.post(f"/me/messages/{draft_id}/send").mock(return_value=httpx.Response(202))
        before = _value(GRAPH_OPERATIONS_TOTAL, operation="outlook_send_draft", status="error")

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await send_draft(
                client,
                confirm=a_person_agrees(cast("Context", cast("object", _CannotAsk()))),
                message_ref=f"outlook:///messages/{draft_id}",
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
            return_value=httpx.Response(200, json=_a_draft(draft_id))
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
            client, confirm=thinks_about_it, message_ref=f"outlook:///messages/{draft_id}"
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

        with measured_graph_operation("get_me"), graph_errors(), graph_step("signed_in_user"):
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

    async def test_a_user_with_no_call_transcripts_is_an_answered_listing_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        _ = graph.route(method="GET", url__regex=r".*/getAllTranscripts\(.*").mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "UnknownError"}}
            )
        )
        labels = {"operation": CALL_TRANSCRIPTS_TOOL, "step": STEP_CALL_TRANSCRIPTS}
        answered = _value(GRAPH_STEPS_TOTAL, **labels, status="ok")
        missing = _value(GRAPH_STEPS_TOTAL, **labels, status="not_found")

        with measured_graph_operation(CALL_TRANSCRIPTS_TOOL, is_refusal=is_refusal):
            found = await teams_list_call_transcripts(client, limit=20)

        assert found.status == "none_found"
        assert _value(GRAPH_STEPS_TOTAL, **labels, status="ok") == answered + 1
        assert _value(GRAPH_STEPS_TOTAL, **labels, status="not_found") == missing

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

        with measured_graph_operation("teams_read_transcript"), graph_errors():
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

        with measured_graph_operation("teams_list_chats"), graph_errors():
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

        with pytest.raises(GraphThrottled), measured_graph_operation("get_me"), graph_errors():
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

        with pytest.raises(GraphThrottled), measured_graph_operation("get_me"), graph_errors():
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

        with pytest.raises(GraphThrottled), measured_graph_operation("get_me"), graph_errors():
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false") == before + 1

    async def test_a_call_that_allows_no_retry_is_not_counted_as_retried(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        sent = graph.get("/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
        before = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false")

        with pytest.raises(GraphThrottled), measured_graph_operation("get_me"), graph_errors():
            _ = await client.me.get(request_configuration=RequestConfiguration(options=no_retry()))

        assert sent.call_count == 1
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

        with measured_graph_operation("teams_list_chats"), graph_errors():
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

        with measured_graph_operation("teams_list_chats"), graph_errors(), graph_step("chats"):
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


_TEAM_ID = "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
_CHANNEL_ID = "19:general@thread.tacv2"
_CHAT_ID = "19:release@thread.v2"

_UNANSWERED = InputRequiredResult(input_requests={}, request_state="state")


async def _send_to_chat(client: GraphServiceClient, answer: Confirmed) -> object:
    async def confirm(question: str, about: str) -> Confirmed:
        assert question and about
        return answer

    with measured_graph_operation(CHAT_SEND_TOOL, is_refusal=is_refusal):
        return await send_chat_message(
            client, chat_id=_CHAT_ID, body_html="Ship it.", confirm=confirm
        )


async def _send_to_channel(client: GraphServiceClient, answer: Confirmed) -> object:
    async def confirm(question: str, about: str) -> Confirmed:
        assert question and about
        return answer

    with measured_graph_operation(CHANNEL_SEND_TOOL, is_refusal=is_refusal):
        return await send_channel_message(
            client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID, body_html="Ship it.", confirm=confirm
        )


class TestATeamsSendIsMeasuredOnlyWhereItPosts:
    @pytest.mark.parametrize("answer", ["Nothing was sent.", _UNANSWERED])
    async def test_a_chat_message_nobody_agreed_to_records_no_send_step(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: Confirmed
    ) -> None:
        posted = graph.post(url__regex=r"/chats/.+/messages$").mock(
            return_value=httpx.Response(201, json={"id": "1700000000001"})
        )
        steps = _value(
            f"{GRAPH_STEP_DURATION_SECONDS}_count", operation=CHAT_SEND_TOOL, step=STEP_CHAT_SEND
        )

        if isinstance(answer, str):
            with pytest.raises(ToolError):
                _ = await _send_to_chat(client, answer)
        else:
            assert await _send_to_chat(client, answer) is answer

        assert posted.call_count == 0
        assert (
            _value(
                f"{GRAPH_STEP_DURATION_SECONDS}_count",
                operation=CHAT_SEND_TOOL,
                step=STEP_CHAT_SEND,
            )
            == steps
        ), "a send that never reached Microsoft Graph was recorded as a send step"

    @pytest.mark.parametrize("answer", ["Nothing was posted.", _UNANSWERED])
    async def test_a_channel_message_nobody_agreed_to_records_no_send_step(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: Confirmed
    ) -> None:
        posted = graph.post(url__regex=r"/channels/.+/messages$").mock(
            return_value=httpx.Response(201, json={"id": "1700000000002"})
        )
        steps = _value(
            f"{GRAPH_STEP_DURATION_SECONDS}_count",
            operation=CHANNEL_SEND_TOOL,
            step=STEP_CHANNEL_SEND,
        )

        if isinstance(answer, str):
            with pytest.raises(ToolError):
                _ = await _send_to_channel(client, answer)
        else:
            assert await _send_to_channel(client, answer) is answer

        assert posted.call_count == 0
        assert (
            _value(
                f"{GRAPH_STEP_DURATION_SECONDS}_count",
                operation=CHANNEL_SEND_TOOL,
                step=STEP_CHANNEL_SEND,
            )
            == steps
        ), "a post that never reached Microsoft Graph was recorded as a send step"

    async def test_a_chat_post_answered_with_no_message_is_an_answered_send_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(url__regex=r"/chats/.+/messages$").mock(return_value=httpx.Response(204))
        sent = _value(GRAPH_STEPS_TOTAL, operation=CHAT_SEND_TOOL, step=STEP_CHAT_SEND, status="ok")

        with pytest.raises(AssertionError, match="answered with no message"):
            _ = await _send_to_chat(client, None)

        assert (
            _value(GRAPH_STEPS_TOTAL, operation=CHAT_SEND_TOOL, step=STEP_CHAT_SEND, status="ok")
            == sent + 1
        )

    async def test_a_channel_post_answered_with_no_message_is_an_answered_send_step(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(url__regex=r"/channels/.+/messages$").mock(return_value=httpx.Response(204))
        sent = _value(
            GRAPH_STEPS_TOTAL, operation=CHANNEL_SEND_TOOL, step=STEP_CHANNEL_SEND, status="ok"
        )

        with pytest.raises(AssertionError, match="answered with no message"):
            _ = await _send_to_channel(client, None)

        assert (
            _value(
                GRAPH_STEPS_TOTAL, operation=CHANNEL_SEND_TOOL, step=STEP_CHANNEL_SEND, status="ok"
            )
            == sent + 1
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


class TestATokenAcquisitionIsCountedUnderTheTool:
    @staticmethod
    def _token(monkeypatch: pytest.MonkeyPatch, failure: Exception | None) -> GraphToken:
        class _Exchange:
            async def __aenter__(self) -> str:
                if failure is not None:
                    raise failure
                return "token"

            async def __aexit__(self, *_: object) -> None:
                return None

        def exchange_for(_scopes: list[str]) -> _Exchange:
            return _Exchange()

        monkeypatch.setattr(caller, "EntraOBOToken", exchange_for)
        return GraphToken("Mail.Read")

    @staticmethod
    def _counts() -> dict[frozenset[tuple[str, str]], float]:
        return _samples(GRAPH_TOKEN_ACQUISITIONS_TOTAL)

    async def test_a_token_counts_once_as_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        token = self._token(monkeypatch, None)
        before = self._counts()

        with measured_graph_operation("zz_mail_tool"):
            async with token as issued:
                assert issued == "token"

        assert _moves(GRAPH_TOKEN_ACQUISITIONS_TOTAL, before, "result") == [
            ("zz_mail_tool", "ok", 1.0)
        ]

    @pytest.mark.parametrize(
        ("failure", "result"),
        [
            (RuntimeError("AADSTS65001: The user or administrator has not consented"), "refused"),
            (ConnectionError("Name or service not known"), "failed"),
        ],
        ids=["entra-refused", "network-failed"],
    )
    async def test_a_failure_counts_once_under_its_result(
        self, monkeypatch: pytest.MonkeyPatch, failure: Exception, result: str
    ) -> None:
        token = self._token(monkeypatch, failure)
        before = self._counts()

        with pytest.raises(TokenExchangeFailed), measured_graph_operation("zz_mail_tool"):
            _ = await token.__aenter__()

        assert _moves(GRAPH_TOKEN_ACQUISITIONS_TOTAL, before, "result") == [
            ("zz_mail_tool", result, 1.0)
        ]


class TestEverySeriesAnAlertCountsStartsAtZero:
    def test_a_registered_tool_has_every_series_before_its_first_call(self) -> None:
        start_operation_series(["zz_never_called_tool"], statuses=GRAPH_STATUSES)
        start_tool_outcomes(["zz_never_called_tool"])

        def started(metric: str, label: str) -> dict[str, float]:
            return {
                dict(labels)[label]: value
                for labels, value in _samples(metric).items()
                if dict(labels).get("operation") == "zz_never_called_tool"
            }

        assert started(GRAPH_OPERATIONS_TOTAL, "status") == dict.fromkeys(GRAPH_STATUSES, 0.0)
        assert started(GRAPH_THROTTLED_TOTAL, "retried") == {"true": 0.0, "false": 0.0}
        assert [
            value
            for labels, value in _samples(GRAPH_SLOW_OPERATIONS_TOTAL).items()
            if dict(labels).get("operation") == "zz_never_called_tool"
        ] == [0.0]
        assert started(TOOL_OUTCOMES_TOTAL, "outcome") == {
            "ok": 0.0,
            "asked": 0.0,
            "cancelled": 0.0,
            "refused": 0.0,
            "graph": 0.0,
            "token": 0.0,
            "error": 0.0,
        }
        assert started(GRAPH_TOKEN_ACQUISITIONS_TOTAL, "result") == {
            "ok": 0.0,
            "refused": 0.0,
            "failed": 0.0,
        }


def _probe_server(client: GraphServiceClient) -> FastMCP[None]:
    server: FastMCP[None] = FastMCP(
        "probe", middleware=[BoundedNameMiddleware(), GraphOperationMiddleware()]
    )

    @server.tool(name="zz_reads_me")
    async def reads_me() -> str:
        with graph_errors():
            me = await client.me.get()
        assert me is not None
        return "read"

    @server.tool(name="zz_refused_by_graph")
    async def refused_by_graph() -> str:
        try:
            with graph_errors():
                _ = await client.me.get()
        except GraphForbidden as refusal:
            raise ToolError("Microsoft refused") from refusal
        return "unreachable"

    @server.tool(name="zz_refused_after_graph")
    async def refused_after_graph() -> str:
        refused = "unreachable"
        try:
            with graph_errors():
                _ = await client.me.get()
        except GraphForbidden:
            refused = "Microsoft refused"
        raise ToolError(refused)

    @server.tool(name="zz_never_calls_graph")
    async def never_calls_graph() -> str:
        raise ToolError("refused before any Graph call")

    @server.tool(name="zz_refuses_with_a_cause")
    async def refuses_with_a_cause() -> str:
        try:
            _ = b"\xff".decode()
        except UnicodeDecodeError as error:
            raise ToolError("this page cannot be read as text") from error
        return "unreachable"

    @server.tool(name="zz_recovers_then_crashes")
    async def recovers_then_crashes() -> str:
        try:
            with graph_errors():
                _ = await client.me.get()
        except GraphForbidden:
            pass
        empty: dict[str, str] = {}
        return empty["missing"]

    @server.tool(name="zz_reads_then_crashes")
    async def reads_then_crashes() -> str:
        with graph_errors():
            _ = await client.me.get()
        empty: dict[str, str] = {}
        return empty["missing"]

    @server.tool(name="zz_asserts_inside_graph")
    async def asserts_inside_graph() -> str:
        with graph_errors():
            me = await client.me.get()
            assert me is None, "a connector invariant that does not hold"
        return "unreachable"

    @server.tool(name="zz_needs_an_argument")
    async def needs_an_argument(subject: str) -> str:
        return subject

    @server.tool(name="zz_crashes_inside_a_handler")
    async def crashes_inside_a_handler() -> str:
        try:
            with graph_errors():
                _ = await client.me.get()
        except GraphForbidden:
            empty: dict[str, str] = {}
            return empty["missing"]
        return "unreachable"

    @server.tool(name="zz_asks")
    async def asks() -> InputRequiredResult:
        return InputRequiredResult(
            input_requests={
                "confirmation": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message="Send it?", requested_schema={"type": "object", "properties": {}}
                    )
                )
            },
            request_state="zz",
        )

    @server.tool(name="zz_fails_from_graph")
    async def fails_from_graph() -> str:
        try:
            with graph_errors():
                _ = await client.me.get()
        except GraphForbidden as refusal:
            raise RuntimeError("the connector could not go on") from refusal
        return "unreachable"

    @server.tool(name="zz_returns_an_error")
    async def returns_an_error() -> ToolResult:
        return ToolResult(content="the tool answered with an error", is_error=True)

    @server.tool(name="zz_refuses_with_another_cause")
    async def refuses_with_another_cause() -> str:
        try:
            with graph_errors():
                _ = await client.me.get()
        except GraphForbidden:
            raise ToolError("Microsoft refused") from ValueError("parsed after the refusal")
        return "unreachable"

    @server.tool(name="zz_reads_then_builds_a_bad_answer")
    async def reads_then_builds_a_bad_answer() -> str:
        with graph_errors():
            _ = await client.me.get()
        return str(SignedInUser.model_validate({}))

    @server.tool(name="zz_builds_a_bad_answer")
    async def builds_a_bad_answer() -> str:
        return str(SignedInUser.model_validate({}))

    @server.tool(name="zz_crashes")
    async def crashes() -> str:
        empty: dict[str, str] = {}
        return empty["missing"]

    return server


class TestTheServerCountsEachToolCallUnderItsRegisteredName:
    async def test_a_call_that_reached_graph_is_counted_under_the_tool_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        before = _value(GRAPH_OPERATIONS_TOTAL, operation="zz_reads_me", status="ok")

        async with Client(_probe_server(client)) as mcp:
            _ = await mcp.call_tool("zz_reads_me", {})

        assert _value(GRAPH_OPERATIONS_TOTAL, operation="zz_reads_me", status="ok") == before + 1

    @pytest.mark.parametrize("tool", ["zz_refused_by_graph", "zz_refused_after_graph"])
    async def test_a_refusal_behind_a_graph_failure_is_counted_under_its_remedy(
        self, client: GraphServiceClient, graph: respx.MockRouter, tool: str
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(403, json={}))
        before = _value(GRAPH_OPERATIONS_TOTAL, operation=tool, status="forbidden")

        async with Client(_probe_server(client)) as mcp:
            _ = await mcp.call_tool(tool, {}, raise_on_error=False)

        assert _value(GRAPH_OPERATIONS_TOTAL, operation=tool, status="forbidden") == before + 1

    @pytest.mark.parametrize(
        ("tool", "graph_answer", "not_blamed"),
        [
            ("zz_reads_then_crashes", 200, "ok"),
            ("zz_reads_then_builds_a_bad_answer", 200, "ok"),
            ("zz_recovers_then_crashes", 403, "forbidden"),
            ("zz_crashes_inside_a_handler", 403, "forbidden"),
        ],
    )
    async def test_a_crash_after_graph_answered_is_counted_as_an_error_and_not_as_graph(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        tool: str,
        graph_answer: int,
        not_blamed: str,
    ) -> None:
        _ = graph.get("/me").mock(
            return_value=httpx.Response(graph_answer, json=_ME if graph_answer == 200 else {})
        )
        errors = _value(GRAPH_OPERATIONS_TOTAL, operation=tool, status="error")
        blamed = _value(GRAPH_OPERATIONS_TOTAL, operation=tool, status=not_blamed)

        async with Client(_probe_server(client)) as mcp:
            answered = await mcp.call_tool(tool, {}, raise_on_error=False)

        assert answered.is_error
        assert _value(GRAPH_OPERATIONS_TOTAL, operation=tool, status="error") == errors + 1
        assert _value(GRAPH_OPERATIONS_TOTAL, operation=tool, status=not_blamed) == blamed

    async def test_a_call_that_never_reached_graph_is_not_counted(
        self, client: GraphServiceClient
    ) -> None:
        async with Client(_probe_server(client)) as mcp:
            _ = await mcp.call_tool("zz_never_calls_graph", {}, raise_on_error=False)
            _ = await mcp.call_tool("zz_no_such_tool", {}, raise_on_error=False)

        counted = {dict(labels)["operation"] for labels in _samples(GRAPH_OPERATIONS_TOTAL)}
        assert "zz_never_calls_graph" not in counted
        assert not {"zz_no_such_tool", UNRESOLVED_NAME} & counted


class TestEachToolCallIsCountedUnderHowItEnded:
    @pytest.mark.parametrize(
        ("tool", "graph_answer", "outcome"),
        [
            ("zz_reads_me", 200, "ok"),
            ("zz_refused_by_graph", 403, "graph"),
            ("zz_refused_after_graph", 403, "refused"),
            ("zz_crashes_inside_a_handler", 403, "error"),
            ("zz_never_calls_graph", None, "refused"),
            ("zz_refuses_with_a_cause", None, "refused"),
            ("zz_crashes", None, "error"),
            ("zz_recovers_then_crashes", 403, "error"),
            ("zz_reads_then_crashes", 200, "error"),
            ("zz_asserts_inside_graph", 200, "error"),
            ("zz_needs_an_argument", None, "refused"),
            ("zz_asks", None, "asked"),
            ("zz_fails_from_graph", 403, "graph"),
            ("zz_refuses_with_another_cause", 403, "graph"),
            ("zz_returns_an_error", None, "error"),
            ("zz_builds_a_bad_answer", None, "error"),
            ("zz_reads_then_builds_a_bad_answer", 200, "error"),
        ],
    )
    async def test_the_outcome_names_what_ended_the_call(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        tool: str,
        graph_answer: int | None,
        outcome: str,
    ) -> None:
        me = graph.get("/me").mock(
            return_value=httpx.Response(
                graph_answer or 200, json=_ME if graph_answer == 200 else {}
            )
        )
        before = _samples(TOOL_OUTCOMES_TOTAL)

        async with Client(_probe_server(client)) as mcp:
            if outcome == "asked":
                first = await mcp.session.call_tool(tool, {}, allow_input_required=True)
                assert isinstance(first, InputRequiredResult), (
                    "the question never reached the client"
                )
            else:
                answered = await mcp.call_tool(tool, {}, raise_on_error=False)
                assert answered.is_error == (outcome != "ok")
                if tool == "zz_returns_an_error":
                    assert [getattr(part, "text", None) for part in answered.content] == [
                        "the tool answered with an error"
                    ]

        assert me.call_count == (0 if graph_answer is None else 1)

        assert _moves(TOOL_OUTCOMES_TOTAL, before, "outcome") == [(tool, outcome, 1.0)]

    async def test_an_unknown_tool_name_is_not_counted(self, client: GraphServiceClient) -> None:
        before = _samples(TOOL_OUTCOMES_TOTAL)

        async with Client(_probe_server(client)) as mcp:
            _ = await mcp.call_tool("zz_no_such_tool", {}, raise_on_error=False)

        assert _samples(TOOL_OUTCOMES_TOTAL) == before

    async def test_a_refused_token_on_a_registered_tool_never_reaches_graph(
        self, monkeypatch: pytest.MonkeyPatch, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        class _Refused:
            async def __aenter__(self) -> str:
                raise RuntimeError("AADSTS65001: The user or administrator has not consented")

            async def __aexit__(self, *_: object) -> None:
                return None

        def exchange_for(_scopes: list[str]) -> _Refused:
            return _Refused()

        monkeypatch.setattr(caller, "EntraOBOToken", exchange_for)
        me = graph.get("/me")
        server: FastMCP[None] = FastMCP(
            "probe", middleware=[BoundedNameMiddleware(), GraphOperationMiddleware()]
        )
        get_me.register(server, transport)
        refused = _value(GRAPH_TOKEN_ACQUISITIONS_TOTAL, operation="get_me", result="refused")
        before = _samples(TOOL_OUTCOMES_TOTAL)

        async with Client(server) as mcp:
            _ = await mcp.call_tool("get_me", {}, raise_on_error=False)

        assert me.call_count == 0
        assert (
            _value(GRAPH_TOKEN_ACQUISITIONS_TOTAL, operation="get_me", result="refused")
            == refused + 1
        )
        assert _moves(TOOL_OUTCOMES_TOTAL, before, "outcome") == [("get_me", "token", 1.0)]


class TestACancelledCallIsCounted:
    async def test_a_cancelled_call_is_counted_and_still_cancels(self) -> None:
        async def cancelled(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
            raise asyncio.CancelledError(context.method)

        context = MiddlewareContext(
            message=CallToolRequestParams(name="zz_cancelled_tool", arguments={}),
            method="tools/call",
        )
        before = _samples(TOOL_OUTCOMES_TOTAL)

        with pytest.raises(asyncio.CancelledError):
            _ = await GraphOperationMiddleware().on_call_tool(context, cancelled)

        assert _moves(TOOL_OUTCOMES_TOTAL, before, "outcome") == [
            ("zz_cancelled_tool", "cancelled", 1.0)
        ]


class TestASlowOperationIsCounted:
    @pytest.mark.parametrize(("seconds", "counted"), [(60.5, 1), (60.0, 0), (59.0, 0)])
    def test_only_an_operation_past_sixty_seconds_counts(
        self, seconds: float, counted: int
    ) -> None:
        before = _value(GRAPH_SLOW_OPERATIONS_TOTAL, operation="zz_slow_tool")

        record_graph_call("zz_slow_tool", status="ok", seconds=seconds)

        assert _value(GRAPH_SLOW_OPERATIONS_TOTAL, operation="zz_slow_tool") == before + counted


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
        "site_search",
        "site_by_url",
        "site_drives",
        "site_lists",
        "list_columns",
        "read_list",
        "list_items",
        "list_item",
        "create_list_item",
        "update_list_item",
        "delete_list_item",
        "my_drive",
        "my_drives",
        "folder_children",
        "drive_item",
        "drive_content",
        "shared_item",
        "create_folder",
        "create_text_file",
        "rename_item",
        "move_item",
        "copy_item",
        "delete_item",
        "create_link",
        "invite",
        "chats",
        "chat",
        "chat_messages",
        "chat_call_events",
        "call_transcripts",
        "home_tenant",
        "chat_members",
        "joined_teams",
        "team",
        "channels",
        "channel",
        "channel_messages",
        "chat_message",
        "channel_message",
        "channel_reply",
        "channel_replies",
        "channel_files_folder",
        "send_chat_message",
        "send_channel_message",
        "reply_channel_message",
        "react_to_message",
        "edit_message",
        "delete_message",
        "search_query",
        "resolve_meeting",
        "transcripts",
        "recordings",
        "attendance_reports",
        "attendance_records",
        "create_meeting",
        "update_meeting",
        "delete_meeting",
        "create_chat",
        "add_chat_member",
        "chat_member",
        "remove_chat_member",
        "rename_chat",
        "mail_search",
        "mail_ids",
        "mail_message",
        "message_attachments",
        "message_attachment",
        "attachment_content",
        "mail_folders",
        "people_search",
        "mail_participants",
        "thread_anchor",
        "thread_folder_messages",
        "thread_messages",
        "mail_folder",
        "folder_messages",
        "mail_tips",
        "focused_overrides",
        "mailbox_settings",
        "mail_rules",
        "mail_categories",
        "categories",
        "create_category",
        "delete_category",
        "time_zones",
        "mark_message",
        "move_message",
        "copy_message",
        "rename_folder",
        "move_folder",
        "write_focused_override",
        "destination_folder",
        "create_draft",
        "create_reply",
        "fill_reply",
        "create_reply_all",
        "fill_reply_all",
        "read_draft",
        "update_draft",
        "send_draft",
        "read_mailbox_settings",
        "write_automatic_reply",
        "read_mail_rule",
        "disable_mail_rule",
        "create_mail_rule",
        "update_mail_rule",
        "delete_mail_rule",
        "rule_folder",
        "transcript_attributed",
        "transcript_unattributed",
        "calendar",
        "calendars",
        "calendar_groups",
        "reminder_view",
        "calendar_events",
        "calendar_event",
        "event_attachments",
        "event_attachment",
        "event_attachment_content",
        "create_event",
        "update_event",
        "cancel_event",
        "respond_to_invite",
        "forward_event",
        "delete_event",
        "delete_calendar",
        "calendar_permissions",
        "share_calendar",
        "calendar_permission",
        "unshare_calendar",
        "get_schedule",
        "find_meeting_times",
        "rooms",
        "contacts",
        "contact",
        "create_contact",
        "update_contact",
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
            + "(shared/identity.py, shared/teams/meetings.py) have stopped naming their own — find "
            + "where their step went before assuming this rule still covers them"
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
            GRAPH_TOKEN_ACQUISITIONS_TOTAL,
            GRAPH_SLOW_OPERATIONS_TOTAL,
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
            GRAPH_TOKEN_ACQUISITIONS_TOTAL,
            GRAPH_SLOW_OPERATIONS_TOTAL,
        } - queried
        assert not unplotted, (
            f"{sorted(unplotted)} is recorded on every call and shown to nobody. Either add the "
            + "panel or stop paying for the series."
        )


_HISTOGRAMS = frozenset(
    {GRAPH_OPERATION_DURATION_SECONDS, GRAPH_STEP_DURATION_SECONDS, GRAPH_PAGES_SCANNED}
)


def _instrument(sample: str) -> str:
    for suffix in _PROMETHEUS_SUFFIXES:
        if sample.endswith(suffix) and sample[: -len(suffix)] in _HISTOGRAMS:
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
