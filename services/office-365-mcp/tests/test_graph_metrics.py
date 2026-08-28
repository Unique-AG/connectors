"""The Graph metrics, asserted on a scrape of the registry `/metrics` actually serves.

Trap: `configure_metrics` aims its Prometheus reader at `unique_toolkit.monitoring.REGISTRY`, not
`prometheus_client`'s default. An empty registry answers 200, so a test that read the default
registry would pass with every instrument unbound.

Every assertion is a delta: the registry is process-wide and cumulative, and the rest of the suite
drives the same operation names.
"""

import ast
import json
import pathlib
import re
from collections.abc import AsyncGenerator, Iterator, Mapping, Sequence
from typing import TypeGuard, cast

import httpx
import pytest
import respx
from kiota_http.middleware import retry_handler
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

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

CALLER_TOKEN = "synthetic-graph-access-token"

_CHATS_PATH = "/me/chats"
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
    """Idempotent and not torn down: an OpenTelemetry meter provider can be installed once per
    process."""
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
    """The `le` labels one scrape carries for a histogram, as they are rendered."""
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
        """The buckets are the whole of what these histograms can say about a throttled call.

        Both time the SDK's `Retry-After` waits along with the call: `GraphSettings` documents four
        attempts at its 30 s request timeout, and each wait between them is capped at kiota's
        `RetryHandlerOption.MAX_DELAY` of 180 s. At `prometheus_client`'s default ceiling of 10 s
        every one of those lands in `+Inf` and a throttled call cannot be told apart from a slow one
        — which is the distinction the panel exists to draw. The same layout `app.py` hands
        `setup_ops` for the inbound histogram, so the three can be read against each other without
        correcting for the boundaries.

        Both instruments, because they share one bucket tuple in `metrics.py` on purpose — an
        operation and the steps inside it are only comparable on one scale, and a view added for one
        of them without the other is how that stops being true.

        Asserted on the scrape rather than on `_VIEWS`, for the reason the inbound twin in
        `test_app.py` gives: a histogram's layout is registered once per process, so the argument
        is only correct if it arrived first, and only the scrape says whether it did.
        """
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
        """Counted by remedy rather than by code: 403 and 401 are one remedy and 404 another, and
        the codes Graph can answer with are open-ended."""
        _ = graph.get("/me").mock(return_value=httpx.Response(403, json={}))
        before = _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="forbidden")

        with pytest.raises(GraphForbidden), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_OPERATIONS_TOTAL, operation="get_me", status="forbidden") == before + 1

    async def test_a_step_with_no_operation_above_it_is_not_counted_under_a_made_up_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """An `operation="unknown"` bucket reads on a dashboard as a real operation with real
        latency, so nothing is recorded instead."""
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        before = _samples(GRAPH_OPERATIONS_TOTAL)
        steps = _samples(GRAPH_STEPS_TOTAL)

        with graph_step("signed_in_user"):
            _ = await client.me.get()

        assert _samples(GRAPH_OPERATIONS_TOTAL) == before
        assert _samples(GRAPH_STEPS_TOTAL) == steps


class TestOneGraphCallInsideAToolIsMeasuredOnItsOwn:
    """A second pair of instruments rather than a `step` label on the first: adding one to
    `graph_operations_total` would silently turn every dashboard's operation rate into a Graph-call
    rate under an unchanged expression.
    """

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
        """`read_transcript`'s shape. Under two `graph_errors` blocks the first refusal counted as
        a failed *operation*, so any alert on refusals fired on a tenant behaving as designed."""
        _ = graph.get("/me").mock(
            side_effect=[httpx.Response(403, json={}), httpx.Response(200, json=_ME)]
        )
        answered = _value(GRAPH_OPERATIONS_TOTAL, operation="read_transcript", status="ok")
        refused_operations = _value(
            GRAPH_OPERATIONS_TOTAL, operation="read_transcript", status="forbidden"
        )
        refused_steps = _value(
            GRAPH_STEPS_TOTAL,
            operation="read_transcript",
            step="transcript_attributed",
            status="forbidden",
        )

        with graph_errors("read_transcript"):
            try:
                with graph_step("transcript_attributed"):
                    _ = await client.me.get()
            except GraphForbidden:
                with graph_step("transcript_unattributed"):
                    _ = await client.me.get()

        assert (
            _value(GRAPH_OPERATIONS_TOTAL, operation="read_transcript", status="ok") == answered + 1
        )
        assert (
            _value(GRAPH_OPERATIONS_TOTAL, operation="read_transcript", status="forbidden")
            == refused_operations
        ), "the tool answered, so the operation is not a refusal"
        assert (
            _value(
                GRAPH_STEPS_TOTAL,
                operation="read_transcript",
                step="transcript_attributed",
                status="forbidden",
            )
            == refused_steps + 1
        ), "the refusal is real and belongs to the attempt that was refused"


class TestTheOperationLabelIsANameThisCodeChose:
    async def test_no_graph_series_carries_a_url_a_path_or_a_resource_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph URLs here are made of almost nothing but ids, so a label taken off one is a new
        time series per chat, per message and per meeting, and an unbounded label set takes the
        Prometheus down. `python_http_requests_total` already has this shape."""
        chat_id = "19%3Aunbounded-cardinality%40thread.v2"
        _ = graph.get(f"/chats/{chat_id}").mock(return_value=httpx.Response(200, json={"id": "c"}))

        with graph_errors("list_chats"):
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
        """Under the SDK's ceiling, so it waited and retried: the remedy is quota, not patience."""
        graph.get("/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
        before = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true") == before + 1

    @pytest.mark.usefixtures("no_retry_waiting")
    async def test_a_503_that_named_a_delay_is_counted_as_throttling_and_not_as_an_outage(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph rate limits with a 503 carrying `Retry-After` as well as with a 429. Counted under
        `status="unavailable"` that reads as Microsoft being down while the fix is quota."""
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
        """`RetryHandler` refuses a delay at or past 180 s, so this 429 was never retried at all.
        The answer is available later, which is the opposite remedy to the case above."""
        graph.get("/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "600"}))
        before = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false") == before + 1


class TestAPagedWalkReportsWhatItRead:
    async def test_the_pages_a_walk_read_include_the_callers_own_first_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The item cap bounds a walk, so the request count it costs is only visible here."""
        second = f"{GRAPH_V1}/me/chats?$skiptoken=two"
        third = f"{GRAPH_V1}/me/chats?$skiptoken=three"
        graph.get(_CHATS_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_page(["c-1"], second)),
                httpx.Response(200, json=_page(["c-2"], third)),
                httpx.Response(200, json=_page(["c-3"])),
            ]
        )
        before = _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="list_chats")

        with graph_errors("list_chats"):
            await _walk_chats(client, limit=50)

        assert _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="list_chats") == before + 3

    async def test_a_nested_unnamed_block_does_not_erase_the_name_in_scope(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`graph_errors` blocks nest: `tools/get_me.py` opens a named one around the unnamed one
        in `shared/identity.py`. An inner block with nothing to say about the operation must leave
        the name alone, or a walk one level down goes quiet without anything failing."""
        graph.get(_CHATS_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_page(["c-1"], f"{GRAPH_V1}/me/chats?$skiptoken=two")),
                httpx.Response(200, json=_page(["c-2"])),
            ]
        )
        pages = _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="list_chats")
        counted = _value(GRAPH_OPERATIONS_TOTAL, operation="list_chats", status="ok")

        steps = _value(GRAPH_STEPS_TOTAL, operation="list_chats", step="chats", status="ok")

        with graph_errors("list_chats"), graph_step("chats"):
            await _walk_chats(client, limit=50)

        assert _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="list_chats") == pages + 2
        assert _value(GRAPH_OPERATIONS_TOTAL, operation="list_chats", status="ok") == counted + 1, (
            "the inner block is a step, so it counts against the step instruments and leaves the "
            + "operation counted once — otherwise a tool that names its calls would look like a "
            + "tool called several times"
        )
        assert (
            _value(GRAPH_STEPS_TOTAL, operation="list_chats", step="chats", status="ok")
            == steps + 1
        )


_SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "office_365_mcp"
_TOOLS = _SOURCE_ROOT / "tools"


def _tool_sources() -> list[pathlib.Path]:
    return sorted(path for path in _TOOLS.glob("*.py") if path.name != "__init__.py")


def _source_modules() -> list[pathlib.Path]:
    """`__init__.py` is kept here and dropped in `_tool_sources` above: the rule this feeds is
    about any module that can reach `graph_errors`, and the tool registry can."""
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
    """Bare or through the module it lives in: both spellings compile."""
    if not isinstance(node, ast.Call):
        return False
    called = node.func
    if isinstance(called, ast.Name):
        return called.id == name
    return isinstance(called, ast.Attribute) and called.attr == name


class TestEveryToolNamesItselfWhenItCallsGraph:
    """What `graph_errors`' signature cannot say is that the name has to be *this tool's own*:
    `graph_errors("get_me")` inside `list_chats.py` type-checks, compiles, and files one tool's
    latency under another's name. Asserted through the AST, so a call written across two lines
    counts and a `graph_errors` inside a docstring does not.
    """

    def test_the_tools_are_actually_there(self) -> None:
        """No tool files means every assertion below passes over nothing."""
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
    """Whether this argument is the module's own `TOOL_NAME`, and not a literal spelled again."""
    return isinstance(argument, ast.Name) and argument.id == "TOOL_NAME"


class TestNoOperationNameIsTakenFromData:
    """Only a tool can be held to naming itself — `shared/identity.py` names nothing on purpose —
    but any module under `src/` can pass *data* as the name, which is why this is a second rule and
    not a wider glob on the one above.

    The argument's shape is what is checked: a string literal, or a name this module binds to one at
    module level. Stronger than any test of the recorded samples, because the label only leaks on
    the day a caller passes a live id and no test drives that day.
    """

    def test_the_rule_reaches_past_the_tools_directory(self) -> None:
        """`shared/identity.py` and `shared/meetings.py` are the callers outside `tools/` today,
        both through `graph_step`. If they stop calling it, this rule needs another witness rather
        than a narrower glob."""
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
            # `graph_errors(**named)`: reported as the mapping rather than as nothing, so the
            # message names the expression.
            return keyword.value
    return None


def _module_level_strings(module: ast.Module) -> dict[str, str]:
    """Top level only and a literal only: a local or a parameter of the same name could hold
    anything a caller passed. The values come back too, because the step vocabulary below reads
    them.
    """
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


# Every step name this service is signed off to emit; an exact set rather than a ceiling, which
# would absorb growth silently. The budget: `graph_steps_total` is (operation, step) pairs x
# statuses and `graph_step_duration_seconds` is those pairs x buckets.
GRAPH_STEPS = frozenset(
    {
        "signed_in_user",
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
        "mark_message",
        "move_message",
        "destination_folder",
        "create_draft",
        "create_reply",
        "fill_reply",
        "transcript_attributed",
        "transcript_unattributed",
    }
)

# `STEP` for a module with one, `STEP_<NAME>` for a module that names several.
_STEP_CONSTANT = re.compile(r"^STEP(_[A-Z0-9_]+)?$")

# A bound on shape, not on cardinality (`GRAPH_STEPS` is that), so a step cannot arrive spelled like
# a URL or an id and pass the set assertion by being added to it without anyone noticing what it is.
_STEP_VALUE = re.compile(r"^[a-z][a-z0-9_]*$")


def _declared_steps() -> dict[str, str]:
    """Read from the call sites, not collected by matching constant names: a constant called
    anything but `STEP` or `STEP_*` is still a name this file can read, so matching on the name
    would let it pass the shape rule and stay invisible to the budget below.
    """
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
    """`step` multiplies against `operation`, so a step read off an argument is one time series per
    chat on both step instruments at once. The shape rule below bounds nothing globally — a module
    can declare five hundred module-level constants and pass them all — so the vocabulary is pinned
    to an exact set as well.
    """

    def test_there_are_steps_to_read(self) -> None:
        """No declared steps means every assertion here passes over nothing."""
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
        """Deliberately not the bound: the budget above reads the value that reaches the label, so
        a constant named anything at all is still counted. This keeps them findable by grep."""
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
    """`graph_step` takes it first and positionally; `graph_errors` takes it only by keyword, so a
    positional argument there is the operation and never a step."""
    if _is_graph_step(call) and call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "step":
            return keyword.value
        if keyword.arg is None:
            # `graph_step(**named)`: as above.
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

# Prometheus renders a histogram as `_bucket`, `_count` and `_sum`, so a panel naming one of those
# names the instrument.
_GRAPH_METRIC_IN_A_QUERY = re.compile(r"\bgraph_[a-z_]+\b")
_PROMETHEUS_SUFFIXES = ("_bucket", "_count", "_sum")


def _panels() -> list[Mapping[str, object]]:
    dashboard = cast("Mapping[str, object]", json.loads(_DASHBOARD.read_text()))
    panels = dashboard.get("panels")
    assert isinstance(panels, list), f"the dashboard has no panel list, got {type(panels)}"
    return [panel for panel in cast("list[object]", panels) if isinstance(panel, Mapping)]


def _queries(panel: Mapping[str, object]) -> list[str]:
    """Read from the panel's `expr` fields rather than the file's text: a panel *description* is
    prose, and prose about `graph_client/observability.py` is not a query for a series called
    `graph_client`."""
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
    """`graph_requests_total` became `graph_operations_total` here. A Prometheus query for a metric
    nobody exports is an empty result and not a failure, so every panel naming the old series would
    have gone on rendering empty, and a blank panel looks like an idle service.
    """

    def test_the_dashboard_is_readable_json(self) -> None:
        """An unreadable or moved file would make the rules below vacuous."""
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
        """The rule in the other direction: an instrument nobody plots was paid for and not read."""
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


# A panel titled "Graph calls/min" over `graph_operations_total` was counting tool calls and calling
# them Graph calls, which is the reading the `graph_requests_total` rename was meant to end.
_A_CALL_IN_A_TITLE = re.compile(r"\bcalls?\b", re.IGNORECASE)

# The two series that count a Graph call; everything else `graph_*` counts an operation, a page or
# a 429.
_STEP_LEVEL = frozenset({GRAPH_STEPS_TOTAL, GRAPH_STEP_DURATION_SECONDS})


def _panel_graph_metrics(panel: Mapping[str, object]) -> set[str]:
    return {_instrument(name) for query in _queries(panel) for name in _metric_names(query)}


class TestNoPanelPromisesGraphCallsAndPlotsOperations:
    """A wrong title is worse than an empty panel: it renders a real number a reader takes for a
    different measurement. `list_meeting_recordings` makes three Graph calls per invocation, so an
    operation rate read as a Graph call rate understates Graph traffic by the fan-out.
    """

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
        """The other direction: the call axis has to exist, or the rule above just deletes it."""
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


# How a dashboard query says "count this as a failure": everything except the statuses it names.
_EXCLUDED_STATUSES = re.compile(r'status!~\\?"([a-z_|]+)\\?"')


class TestTheDashboardDecidesAboutEveryStatusTheCodeCanEmit:
    """`cancelled` is why this exists. The dashboard half of a status is a set of negative filters
    spelled `status!~"ok|not_found"`, and a status nobody added to one counts as a failure by
    default: right for a status that *is* a failure, wrong for an MCP client hanging up.
    """

    def test_every_error_query_excludes_the_statuses_that_are_not_failures(self) -> None:
        not_failures = {"ok", "not_found", "cancelled"}
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
        """The other direction: a typo in an exclusion silently stops excluding anything."""
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
