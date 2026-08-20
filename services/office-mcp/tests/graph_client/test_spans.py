"""What a Graph request span is allowed to say about the resource it asked for.

Kiota labels a Graph URL as EUII and sets it as `url.full` by default, in two places: the request
span the adapter opens, and the span `UrlReplaceHandler` opens for itself. In this service a Graph
URL carries chat ids, message ids and meeting/transcript ids, so with tracing switched on those ids
would be exported to a trace backend and kept there. `graph_client_for` closes the first,
`_QuietUrlReplaceHandler` the second; these tests are what says so, over real SDK calls rather than
over the option object.

The last class here asserts nothing about a span. `_QuietUrlReplaceHandler` is a copy of an SDK
method, and a copy needs something watching the original: that class reads the upstream source and
fails when it changes shape, which is the only way an msgraph or kiota bump can announce that the
copy has fallen behind.
"""

import ast
import inspect
import textwrap
from collections.abc import Iterator, Sequence

import httpx
import pytest
import respx
from kiota_http.middleware.url_replace_handler import UrlReplaceHandler
from msgraph.graph_service_client import GraphServiceClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# Both survive percent-encoding unchanged, which is the point: the id reaches the URL as
# `19%3Aleak-detector%40thread.v2`, so a test that looked for the id verbatim would miss it.
_CHAT_ID = "19:leak-detector@thread.v2"
_MESSAGE_ID = "1770000000042"
_RESOURCE_IDS = ("leak-detector", _MESSAGE_ID)

_REQUEST_PATH = "/chats/19%3Aleak-detector%40thread.v2/messages/1770000000042"

# The span the URL replacer opens for itself. It is named here because it is the one span this
# service replaces a handler to clean: `UrlReplaceHandler.send` sets `url.full` on it without
# consulting `ObservabilityOptions` at all (kiota_http/middleware/url_replace_handler.py:44), so the
# option the adapter is given cannot reach it. The span itself is wanted and is asserted below —
# the fix drops one attribute, not the telemetry.
_URL_REPLACER_SPAN = "UrlReplaceHandler_send"


@pytest.fixture
def recorded_spans() -> Iterator[InMemorySpanExporter]:
    """Every span this process finishes from here on, collected in memory.

    The tracer provider is process-wide and can only be set once, so the exporter is attached to
    whichever one is already in play and the collection is emptied on the way in rather than torn
    down — a span from an earlier test would otherwise read as one of this test's own.
    """
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    exporter.clear()
    yield exporter


async def _read_one_message(client: GraphServiceClient, graph: respx.MockRouter) -> None:
    """One `GET /chats/{chat}/messages/{message}`, which is a URL made of nothing but ids."""
    _ = graph.get(_REQUEST_PATH).mock(return_value=httpx.Response(200, json={"id": _MESSAGE_ID}))
    _ = await client.chats.by_chat_id(_CHAT_ID).messages.by_chat_message_id(_MESSAGE_ID).get()


def _spans_naming_a_resource(spans: Sequence[ReadableSpan]) -> set[str]:
    """The names of the spans that carry a chat or message id in an attribute."""
    return {
        span.name
        for span in spans
        if any(resource in str(span.attributes) for resource in _RESOURCE_IDS)
    }


def _spans_carrying_the_url(spans: Sequence[ReadableSpan]) -> set[str]:
    """The names of the spans that carry a `url.full` attribute, whatever its value."""
    return {span.name for span in spans if "url.full" in (span.attributes or {})}


class TestAGraphRequestSpanNamesTheTemplateAndNotTheResource:
    async def test_the_request_span_carries_the_template_it_called_and_no_id(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """The span a trace backend shows as "the Graph request" is the one this is about.

        Both halves matter. The template has to still be there, or the way to make this test pass
        would be to stop tracing Graph calls at all — and grouping a latency breakdown by URL
        template is the whole reason the span is worth having.
        """
        await _read_one_message(client, graph)

        requests = [
            span for span in recorded_spans.get_finished_spans() if "send_async" in span.name
        ]
        assert len(requests) == 1, "one call, one request span — otherwise this asserts on nothing"
        attributes = requests[0].attributes or {}
        assert "url.uri_template" in attributes, "the call still has to be traced"
        assert "url.full" not in attributes
        for resource in _RESOURCE_IDS:
            assert resource not in str(attributes), f"{resource} reached {requests[0].name}"

    async def test_no_span_at_all_carries_the_url_or_a_resource_id(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """The claim over the whole trace, not over the one span this connector asked for.

        The SDK opens a span per middleware as well as per request, so a dozen spans reach the
        exporter for one call. Asserting the empty set is what makes a new leak fail: a handler
        added by a later SDK version that sets `url.full`, or this service losing
        `_QuietUrlReplaceHandler` in a refactor, both land here.
        """
        await _read_one_message(client, graph)

        spans = recorded_spans.get_finished_spans()
        assert spans, "no span was recorded, so this test proves nothing"
        assert _spans_carrying_the_url(spans) == set(), (
            "a span is exporting the Graph URL, which here is a chat and a message id"
        )
        assert _spans_naming_a_resource(spans) == set(), (
            "a span attribute is exporting a Graph resource id to the trace backend"
        )


class TestTheUrlReplacerIsQuietenedAndNotSwitchedOff:
    async def test_it_still_opens_its_span_and_still_rewrites_me(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """Both of the things a shortcut would have cost.

        Dropping the handler, or disabling it, would also silence the leak — and would take the
        `/users/me-token-to-replace` → `/me` rewrite with it, which every `client.me` call depends
        on. Dropping its span instead of its one attribute would silence the leak by exporting
        less telemetry. The route below is asserted called because it is mounted on `/me`: the SDK
        asks for `/users/me-token-to-replace` and only the handler turns that into `/me`.
        """
        route = graph.get("/me").mock(return_value=httpx.Response(200, json={"id": "u-1"}))

        _ = await client.me.get()

        assert route.called, (
            "the /me rewrite is gone, so the handler was disabled and not subclassed"
        )
        replacer = [
            span for span in recorded_spans.get_finished_spans() if span.name == _URL_REPLACER_SPAN
        ]
        assert len(replacer) == 1, "the handler's own span is still wanted, minus the URL"
        attributes = replacer[0].attributes or {}
        assert attributes.get("com.microsoft.kiota.handler.url_replacer.enable") is True
        assert "url.full" not in attributes


# `UrlReplaceHandler.send` as the installed SDK writes it, printed back from its own AST so that a
# reformat or a docstring edit upstream does not fail the test below and every change of substance
# does. `_QuietUrlReplaceHandler.send` is these statements minus the one that sets `url.full`.
_UPSTREAM_SEND_BODY = """\
response = None
_enable_span = self._create_observability_span(request, 'UrlReplaceHandler_send')
if self.options and self.options.is_enabled:
    _enable_span.set_attribute('com.microsoft.kiota.handler.url_replacer.enable', True)
    current_options = self._get_current_options(request)
    url_string: str = str(request.url)
    url_string = self.replace_url_segment(url_string, current_options)
    request.url = httpx.URL(url_string)
    _enable_span.set_attribute(URL_FULL, str(request.url))
response = await super().send(request, transport)
_enable_span.end()
return response"""

# Where a reader has to go when one of the three assertions below fails. Spelled once, because all
# three send them to the same two places and the point of the failure is to be actionable.
_WHAT_TO_REREAD = (
    "Re-read kiota_http/middleware/url_replace_handler.py's UrlReplaceHandler.send and then "
    "_QuietUrlReplaceHandler.send in src/office_mcp/graph_client/client.py, which is a copy of it "
    "minus the one line that puts the Graph URL on a span. Whatever the SDK gained has to be "
    "gained in the copy, or this service silently stops doing it; whatever it lost may make the "
    "copy unnecessary. Then update _UPSTREAM_SEND_BODY here to the new shape."
)


def _upstream_send() -> ast.AsyncFunctionDef:
    """The SDK's own `send`, parsed from the source of the installed package."""
    parsed = ast.parse(textwrap.dedent(inspect.getsource(UrlReplaceHandler.send))).body[0]
    assert isinstance(parsed, ast.AsyncFunctionDef), (
        f"kiota's UrlReplaceHandler.send is no longer an async def. {_WHAT_TO_REREAD}"
    )
    return parsed


def _statements(method: ast.AsyncFunctionDef) -> str:
    """The method's body without its docstring, normalised through the AST."""
    body = method.body[1:] if ast.get_docstring(method) is not None else method.body
    return ast.unparse(ast.Module(body=body, type_ignores=[]))


def _url_attribute_sets(method: ast.AsyncFunctionDef) -> list[str]:
    """Every line of `method` that puts the request URL on a span, however it is spelled."""
    return [
        ast.unparse(call)
        for call in ast.walk(method)
        if isinstance(call, ast.Call)
        and ast.unparse(call.func).endswith(".set_attribute")
        and call.args
        and ast.unparse(call.args[0]) in ("URL_FULL", "'url.full'")
    ]


class TestTheSdkMethodThisServiceCopiedIsStillTheMethodItCopied:
    """The one thing neither the spans above nor the assembled chain in `test_client.py` can see.

    That chain comparison fails when the SDK *adds* a handler. These spans fail when a handler
    exports a URL. Between them sits the case that fails nothing: `UrlReplaceHandler.send` gaining a
    line, losing one, or delegating differently. `_QuietUrlReplaceHandler` mirrors that method minus
    one `set_attribute`, so an msgraph or kiota bump can leave the copy quietly behind — still
    correct about the leak, no longer doing whatever the original started doing. Reading the
    upstream source is the only way to notice, so that is what these three do.
    """

    def test_exactly_one_line_puts_the_url_on_a_span_and_it_is_the_one_removed(self) -> None:
        """The whole reason the copy exists. Two such lines and the copy drops one and keeps the
        other; none, and the copy is dead weight that should go back to the SDK's own handler."""
        sets = _url_attribute_sets(_upstream_send())

        assert len(sets) == 1, (
            f"UrlReplaceHandler.send now sets the URL on its span {len(sets)} time(s), not once: "
            + f"{sets}. {_WHAT_TO_REREAD}"
        )

    def test_the_me_rewrite_the_copy_carries_is_still_there(self) -> None:
        """The behaviour the copy exists to keep. Every `client.me` call depends on it: the SDK
        asks for `/users/me-token-to-replace` and only this handler turns that into `/me`, which is
        why the leak is fixed by subclassing rather than by dropping the handler."""
        body = _statements(_upstream_send())

        assert "self.replace_url_segment(" in body, (
            f"UrlReplaceHandler.send no longer rewrites the URL segment. {_WHAT_TO_REREAD}"
        )
        assert "request.url = httpx.URL(" in body, (
            f"UrlReplaceHandler.send no longer assigns the rewritten URL. {_WHAT_TO_REREAD}"
        )

    def test_nothing_else_about_the_method_has_changed(self) -> None:
        """The catch-all under the two above, which name only what this service already knows to
        care about. A new attribute, a second rewrite, a changed delegation or a swallowed
        exception all arrive as a diff here."""
        assert _statements(_upstream_send()) == _UPSTREAM_SEND_BODY, _WHAT_TO_REREAD
