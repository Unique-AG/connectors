"""What a Graph request span is allowed to say about the resource it asked for.

Kiota labels a Graph URL as EUII and puts it on its spans by default. In this service a Graph URL
carries chat ids, message ids and meeting/transcript ids, so with tracing switched on those ids
would be exported to a trace backend and kept there. `graph_client_for` turns that off; these tests
are what says so, over a real SDK call rather than over the option object.
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

# The one span that still carries the URL, and the whole of why it is named here rather than fixed:
# `UrlReplaceHandler` sets `url.full` on its own span without consulting `ObservabilityOptions` at
# all (kiota_http/middleware/url_replace_handler.py:44), and that handler is what rewrites
# `/users/me-token-to-replace` to `/me`, so it cannot be switched off without taking ownership of
# the SDK's whole middleware pipeline. Removing it needs an upstream fix, or a span filter installed
# where the tracer provider is built. Named as an exact set so that a *new* leak fails this test,
# and so that the day the leak goes the test fails too and this paragraph goes with it.
_SDK_MIDDLEWARE_SPAN_THAT_STILL_CARRIES_THE_URL = "UrlReplaceHandler_send"


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

    async def test_the_url_survives_on_exactly_one_span_and_it_is_the_sdks_own(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """A pin on a known leak, and a tripwire for a new one.

        The SDK opens a span per middleware as well as per request, so "no id in any span
        attribute" is a claim about a dozen spans and not about the one this connector asked for.
        Asserting the exact set is what makes both directions fail loudly: a second span starting to
        carry the URL, and the named one stopping.
        """
        await _read_one_message(client, graph)

        spans = recorded_spans.get_finished_spans()
        assert spans, "no span was recorded, so this test proves nothing"
        assert _spans_naming_a_resource(spans) == {
            _SDK_MIDDLEWARE_SPAN_THAT_STILL_CARRIES_THE_URL
        }, (
            "the set of spans carrying a Graph resource id changed. If it grew, an id is being "
            + "exported to the trace backend. If it shrank to nothing, the SDK stopped setting "
            + "`url.full` in its middleware and this test and the comment above it can go."
        )
