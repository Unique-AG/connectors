"""What a Graph request span is allowed to say about the resource it asked for.

Kiota labels a Graph URL as EUII and sets it as `url.full` by default, in two places: the request
span the adapter opens, and the span `UrlReplaceHandler` opens for itself. A Graph URL here carries
chat, message, meeting and transcript ids. `graph_client_for` closes the first and
`_QuietUrlReplaceHandler` the second.

Asserted over the whole trace rather than over the two mechanisms, which are the part an SDK bump
can move.
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

# Both survive percent-encoding unchanged: the id reaches the URL as
# `19%3Aleak-detector%40thread.v2`, which a test looking for `19:leak-detector@thread.v2` misses.
_CHAT_ID = "19:leak-detector@thread.v2"
_MESSAGE_ID = "1770000000042"
_RESOURCE_IDS = ("leak-detector", _MESSAGE_ID)

_REQUEST_PATH = "/chats/19%3Aleak-detector%40thread.v2/messages/1770000000042"

# `UrlReplaceHandler.send` sets `url.full` on this span without consulting `ObservabilityOptions`
# at all (kiota_http/middleware/url_replace_handler.py:44), so the adapter's option cannot reach it.
_URL_REPLACER_SPAN = "UrlReplaceHandler_send"


@pytest.fixture
def recorded_spans() -> Iterator[InMemorySpanExporter]:
    """The tracer provider is process-wide and settable only once, so the exporter attaches to
    whichever is in play and is emptied on the way in rather than torn down."""
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    exporter.clear()
    yield exporter


async def _read_one_message(client: GraphServiceClient, graph: respx.MockRouter) -> None:
    _ = graph.get(_REQUEST_PATH).mock(return_value=httpx.Response(200, json={"id": _MESSAGE_ID}))
    _ = await client.chats.by_chat_id(_CHAT_ID).messages.by_chat_message_id(_MESSAGE_ID).get()


def _spans_naming_a_resource(spans: Sequence[ReadableSpan]) -> set[str]:
    return {
        span.name
        for span in spans
        if any(resource in str(span.attributes) for resource in _RESOURCE_IDS)
    }


def _spans_carrying_the_url(spans: Sequence[ReadableSpan]) -> set[str]:
    return {span.name for span in spans if "url.full" in (span.attributes or {})}


class TestAGraphRequestSpanNamesTheTemplateAndNotTheResource:
    async def test_the_request_span_carries_the_template_it_called_and_no_id(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """The template has to still be there, or the way to pass this test is to stop tracing
        Graph calls at all."""
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
        """The SDK opens a span per middleware as well as per request, so a dozen spans reach the
        exporter for one call and a leak can appear in any of them."""
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
        """Dropping or disabling the handler would silence the leak and take the
        `/users/me-token-to-replace` to `/me` rewrite with it, which every `client.me` call needs.
        The route is mounted on `/me`, so only the handler makes it match."""
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
