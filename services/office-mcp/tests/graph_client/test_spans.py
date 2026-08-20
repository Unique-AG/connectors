"""What a Graph request span is allowed to say about the resource it asked for.

Kiota labels a Graph URL as EUII and sets it as `url.full` by default, in two places: the request
span the adapter opens, and the span `UrlReplaceHandler` opens for itself. In this service a Graph
URL carries chat ids, message ids and meeting/transcript ids, so with tracing switched on those ids
would be exported to a trace backend and kept there. `graph_client_for` closes the first,
`_QuietUrlReplaceHandler` the second; these tests are what says so, over real SDK calls rather than
over the option object.

Asserted as a property of the whole trace rather than of the two mechanisms, because the mechanisms
are the part an SDK bump can move. A handler added upstream that exports a URL, a spelling of the
attribute the quiet handler's span wrapper does not intercept, or this service losing that handler
in a refactor all land on the same assertion: no span carries `url.full`, and no span attribute
carries a resource id.
"""

from collections.abc import Iterator, Sequence

import httpx
import pytest
import respx
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
