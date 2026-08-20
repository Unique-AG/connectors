"""The Graph metrics, asserted on a scrape of the registry `/metrics` actually serves.

Trap: `configure_metrics` aims its Prometheus reader at `unique_toolkit.monitoring.REGISTRY`, not at
`prometheus_client`'s default one. A test that asked the default registry — or that only asked
whether `/metrics` answers 200 — would pass with every instrument in this service unbound, because
an empty registry answers 200 too. These tests read the same registry object the route reads.

Every assertion is a delta across the call rather than an absolute value: the registry is
process-wide and cumulative, and the rest of the suite drives the same tools under the same
operation names.
"""

import ast
import pathlib
from collections.abc import AsyncGenerator, Iterator, Mapping, Sequence
from typing import TypeGuard

import httpx
import pytest
import respx
from kiota_http.middleware import retry_handler
from msgraph.graph_service_client import GraphServiceClient
from prometheus_client import generate_latest
from unique_toolkit.monitoring import REGISTRY

from office_mcp.config import AppConfig
from office_mcp.graph_client import (
    GRAPH_PAGES_SCANNED,
    GRAPH_REQUEST_DURATION_SECONDS,
    GRAPH_REQUESTS_TOTAL,
    GRAPH_THROTTLED_TOTAL,
    GraphForbidden,
    GraphSettings,
    GraphThrottled,
    collect_pages,
    create_graph_transport,
    graph_client_for,
    graph_errors,
)
from office_mcp.metrics import configure_metrics

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
    """The reader that binds this service's instruments to the toolkit registry.

    Idempotent and shared with every other test that builds the app, which is why it is not torn
    down: an OpenTelemetry meter provider can be installed once per process.
    """
    _ = configure_metrics(
        AppConfig.model_validate({"public_base_url": "https://office-mcp.example"})
    )


@pytest.fixture
def no_retry_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the SDK's retry handler decide to wait without a test waiting for it."""

    class _Instant:
        async def sleep(self, _delay: float) -> None:
            return None

    monkeypatch.setattr(retry_handler, "asyncio", _Instant())


def _samples(metric: str) -> dict[frozenset[tuple[str, str]], float]:
    """One scrape of the registry `/metrics` reads, as {labels: value} for one sample name."""
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
    """The one sample of `metric` carrying every label given, or 0 when there is none yet."""
    wanted = frozenset(labels.items())
    matched = [value for keys, value in _samples(metric).items() if wanted <= keys]
    assert len(matched) <= 1, f"{metric}{labels} matched {len(matched)} series"
    return matched[0] if matched else 0.0


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
        before = _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="ok")
        timed = _value(f"{GRAPH_REQUEST_DURATION_SECONDS}_count", operation="get_me")

        with graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="ok") == before + 1
        assert _value(f"{GRAPH_REQUEST_DURATION_SECONDS}_count", operation="get_me") == timed + 1

    async def test_a_refusal_is_counted_under_its_remedy_and_not_its_status_code(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """403 and 401 are one remedy and 404 is another, which is what `errors.py` sorts them into.

        Counted by remedy rather than by code so that the series stay countable: the codes Graph can
        answer with are open-ended, and a dashboard panel per code is a panel nobody reads.
        """
        _ = graph.get("/me").mock(return_value=httpx.Response(403, json={}))
        before = _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="forbidden")

        with pytest.raises(GraphForbidden), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="forbidden") == before + 1

    async def test_a_call_nobody_named_is_not_counted_under_a_made_up_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """An `operation="unknown"` bucket reads on a dashboard as a real operation with real
        latency, and the tool that forgot to name itself disappears inside it. Nothing is recorded
        instead."""
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        before = _samples(GRAPH_REQUESTS_TOTAL)

        with graph_errors():
            _ = await client.me.get()

        assert _samples(GRAPH_REQUESTS_TOTAL) == before


class TestTheOperationLabelIsANameThisCodeChose:
    async def test_no_graph_series_carries_a_url_a_path_or_a_resource_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The one hazard these metrics could introduce. A label taken off a Graph URL is a new time
        series per chat, per message and per meeting — Graph URLs here are made of almost nothing
        else — and an unbounded label set takes the Prometheus down rather than showing up as a bad
        dashboard. `python_http_requests_total` already has this shape; these must not add to it."""
        chat_id = "19%3Aunbounded-cardinality%40thread.v2"
        _ = graph.get(f"/chats/{chat_id}").mock(return_value=httpx.Response(200, json={"id": "c"}))

        with graph_errors("list_chats"):
            _ = await client.chats.by_chat_id("19:unbounded-cardinality@thread.v2").get()

        families = (
            GRAPH_REQUESTS_TOTAL,
            f"{GRAPH_REQUEST_DURATION_SECONDS}_count",
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
        """A `Retry-After` under the SDK's ceiling: it waited, retried, and the quota was still
        gone. The remedy is quota, not patience."""
        graph.get("/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
        before = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true") == before + 1

    @pytest.mark.usefixtures("no_retry_waiting")
    async def test_a_503_that_named_a_delay_is_counted_as_throttling_and_not_as_an_outage(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The two the operator answers with different money: quota, or an incident.

        Graph rate limits with a 503 carrying `Retry-After` as well as with a 429. Counted under
        `status="unavailable"`, that reads as Microsoft being down while the fix is quota — and
        `graph_throttled_total`, the panel an operator would check next, misses it entirely.
        """
        graph.get("/me").mock(return_value=httpx.Response(503, headers={"Retry-After": "7"}))
        throttled = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true")
        counted = _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="throttled")
        outages = _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="unavailable")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true") == throttled + 1
        assert _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="throttled") == counted + 1
        assert _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="unavailable") == outages

    @pytest.mark.usefixtures("no_retry_waiting")
    async def test_no_retry_attempted_when_graph_asked_for_a_wait_past_the_ceiling(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`RetryHandler` refuses a delay at or past 180 s, so this 429 was never retried at all —
        the answer is available later, which is the opposite remedy to the case above."""
        graph.get("/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "600"}))
        before = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false") == before + 1


class TestAPagedWalkReportsWhatItRead:
    async def test_the_pages_a_walk_read_include_the_callers_own_first_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Three pages for one call is the number worth seeing: the item cap bounds a walk, so the
        request count it costs is only visible here."""
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
        """`graph_errors` blocks nest: `tools/get_me.py` opens a named one around the unnamed one in
        `shared/identity.py`. An inner block with nothing to say about the operation must leave the
        name alone, or a walk one level down becomes uncountable — and it would go quiet without
        anything failing."""
        graph.get(_CHATS_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_page(["c-1"], f"{GRAPH_V1}/me/chats?$skiptoken=two")),
                httpx.Response(200, json=_page(["c-2"])),
            ]
        )
        pages = _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="list_chats")
        counted = _value(GRAPH_REQUESTS_TOTAL, operation="list_chats", status="ok")

        with graph_errors("list_chats"), graph_errors():
            await _walk_chats(client, limit=50)

        assert _value(f"{GRAPH_PAGES_SCANNED}_sum", operation="list_chats") == pages + 2
        assert _value(GRAPH_REQUESTS_TOTAL, operation="list_chats", status="ok") == counted + 1, (
            "the inner block names no operation, so it counts nothing of its own"
        )


_SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "office_mcp"
_TOOLS = _SOURCE_ROOT / "tools"


def _tool_sources() -> list[pathlib.Path]:
    return sorted(path for path in _TOOLS.glob("*.py") if path.name != "__init__.py")


def _source_modules() -> list[pathlib.Path]:
    """Every module this service ships, the ones that are not tools included.

    `__init__.py` is kept, unlike in `_tool_sources` above, where it is dropped because it is the
    tool registry rather than a tool. The rule this feeds is about any module that can reach
    `graph_errors` at all, and a registry can.
    """
    return sorted(_SOURCE_ROOT.rglob("*.py"))


def _source_id(source: pathlib.Path) -> str:
    """Test id for one module: `shared/identity.py`, not an absolute path."""
    return source.relative_to(_SOURCE_ROOT).as_posix()


def _parsed(source: pathlib.Path) -> ast.Module:
    return ast.parse(source.read_text())


def _graph_errors_calls(module: ast.Module) -> list[ast.Call]:
    """Every `graph_errors(...)` in one module, however it was spelled.

    A bare name or a call through the module it lives in, because both compile and only the first
    was looked for while this read nine files that all import it the same way.
    """
    return [node for node in ast.walk(module) if _is_graph_errors(node)]


def _is_graph_errors(node: ast.AST) -> TypeGuard[ast.Call]:
    if not isinstance(node, ast.Call):
        return False
    called = node.func
    if isinstance(called, ast.Name):
        return called.id == "graph_errors"
    return isinstance(called, ast.Attribute) and called.attr == "graph_errors"


class TestEveryToolNamesItselfWhenItCallsGraph:
    """The ratchet under the label, and the reason `operation` is worth having at all.

    `graph_errors` accepts no operation and then records nothing, which is deliberate: a name
    invented for a caller that supplied none would read on a dashboard as a real operation. The cost
    of that choice is that a tool which forgets goes missing from the Graph metrics with nothing
    failing anywhere. This is what fails instead.

    Asserted through the AST rather than on the text, so that a call written across two lines counts
    and a `graph_errors` inside a docstring does not.
    """

    def test_the_tools_are_actually_there(self) -> None:
        """Guards the guard: no tool files means every assertion below passes over nothing."""
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
            + f"{GRAPH_REQUESTS_TOTAL} rather than showing up under a wrong name."
        )


def _names_the_tool(argument: ast.expr) -> bool:
    """Whether this argument is the module's own `TOOL_NAME`, and not a literal spelled again."""
    return isinstance(argument, ast.Name) and argument.id == "TOOL_NAME"


class TestNoOperationNameIsTakenFromData:
    """The same label, over every module rather than over `tools/`, and about what the name is.

    Two different failures, which is why this is a second rule and not a wider glob on the one
    above. A tool that names nothing goes missing from a dashboard, and only a tool can be held to
    naming itself: `shared/identity.py` names nothing on purpose, so that a nested call is counted
    under the tool one level up. Passing *data* as the name is the other failure, it is not
    survivable, and any module under `src/` can do it — `graph_errors(url)` or
    `graph_errors(f"chat_{chat_id}")` is one time series per chat, per message and per meeting, and
    an unbounded label set takes a Prometheus down rather than showing up as a bad dashboard.

    So what is checked is the shape of the argument: a string literal, or a name this module binds
    to one at module level. An f-string, a subscript, an attribute, a call, a splat, or a name that
    is a parameter or a local — anything whose value this file cannot see — fails. Weaker than
    reading the value, and stronger than anything a test of the recorded samples could say: the
    label only leaks on the day a caller passes it a live id, and no test drives that day.
    """

    def test_the_rule_reaches_past_the_tools_directory(self) -> None:
        """Guards the guard twice: that there are modules to read, and that widening the glob was
        load-bearing. `shared/identity.py` is the caller outside `tools/` today. If it stops being
        one, this rule needs another witness rather than a narrower glob."""
        modules = _source_modules()
        assert len(modules) > len(_tool_sources()), f"no modules found under {_SOURCE_ROOT}"
        calling = {_source_id(module) for module in modules if _graph_errors_calls(_parsed(module))}
        assert calling - {_source_id(source) for source in _tool_sources()}, (
            "every graph_errors call is under tools/, so this asserts nothing the tools-only rule "
            + "did not — find the caller that moved before narrowing the glob back"
        )

    @pytest.mark.parametrize("source", _source_modules(), ids=_source_id)
    def test_the_operation_is_a_name_this_code_chose(self, source: pathlib.Path) -> None:
        module = _parsed(source)
        chosen = _module_level_strings(module)
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
            + f"meeting, and an unbounded label set on {GRAPH_REQUESTS_TOTAL} takes the Prometheus "
            + "down rather than showing up as a bad dashboard. Pass a constant this module binds "
            + "at its top level, the way every tool passes its own TOOL_NAME."
        )


def _operation_named(call: ast.Call) -> ast.expr | None:
    """What this call names its operation, or `None` when it names none.

    A call that names none is allowed and records nothing; that is `TestEveryToolNamesItself...`'s
    subject, not this one's.
    """
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "operation":
            return keyword.value
        if keyword.arg is None:
            # `graph_errors(**named)`: the operation may be in there and this file cannot see it.
            # Reported as the mapping rather than as nothing, so the message names the expression.
            return keyword.value
    return None


def _module_level_strings(module: ast.Module) -> frozenset[str]:
    """The names this module binds to a string literal at its top level, `TOOL_NAME` among them.

    Top level only, and a literal only. A module-level name is a decision taken in this file and
    readable in it, which is the whole property `operation` needs; a local or a parameter of the
    same name could hold anything a caller passed.
    """
    return frozenset(
        target.id
        for statement in module.body
        for target in _assigned_names(statement)
        if isinstance(target, ast.Name)
    )


def _assigned_names(statement: ast.stmt) -> list[ast.expr]:
    """The targets of `statement`, when it assigns a string literal, and nothing otherwise."""
    if isinstance(statement, ast.Assign) and _is_string(statement.value):
        return statement.targets
    if (
        isinstance(statement, ast.AnnAssign)
        and statement.value is not None
        and _is_string(statement.value)
    ):
        return [statement.target]
    return []


def _is_string(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_chosen_in_code(named: ast.expr, chosen: frozenset[str]) -> bool:
    """Whether `named` is a value this file decided, rather than one it was handed."""
    if _is_string(named):
        return True
    return isinstance(named, ast.Name) and named.id in chosen
