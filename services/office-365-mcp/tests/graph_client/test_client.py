import httpx
import pytest
import respx
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from kiota_abstractions.request_option import RequestOption
from msgraph.generated.users.item.onenote.pages.pages_request_builder import PagesRequestBuilder
from msgraph.generated.users.item.send_mail.send_mail_post_request_body import (
    SendMailPostRequestBody,
)
from msgraph.graph_request_adapter import options as sdk_middleware_options
from msgraph.graph_service_client import GraphServiceClient
from msgraph_core import GraphClientFactory

from office_365_mcp.graph_client import (
    GraphNotFound,
    GraphSettings,
    GraphThrottled,
    create_graph_transport,
    fetch_response,
    graph_errors,
    native_response,
    no_retry,
    request_with_query,
)
from office_365_mcp.graph_client.client import (
    _CallerTokenProvider,  # pyright: ignore[reportPrivateUsage]
)
from tests.conftest import RecordedSleeps

from .conftest import CALLER_TOKEN, GRAPH_V1


def _resource_content_request(
    client: GraphServiceClient, resource_id: str, *, native: bool = True
) -> RequestInformation:
    builder = client.me.onenote.resources.by_onenote_resource_id(resource_id).content
    request = RequestInformation(Method.GET, builder.url_template, builder.path_parameters)
    request.headers.try_add("Accept", "application/octet-stream, application/json")
    if native:
        request.add_request_options(native_response())
    return request


def _handler_chain(transport: httpx.AsyncClient) -> list[str]:
    """Reaches through private attributes: the SDK exposes no assembled pipeline."""
    handler: object = transport._transport  # pyright: ignore[reportPrivateUsage]
    handler = getattr(getattr(handler, "pipeline", None), "_first_middleware", None)
    names: list[str] = []
    while handler is not None:
        names.append(type(handler).__name__)
        handler = getattr(handler, "next", None)
    return names


class TestTheCallersTokenIsWhatCalls:
    async def test_it_is_sent_to_graph_as_a_bearer_token(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get("/me").mock(
            return_value=httpx.Response(200, json={"id": "u-1", "displayName": "Ada Lovelace"})
        )

        user = await client.me.get()

        assert user is not None
        assert user.display_name == "Ada Lovelace"
        assert route.calls.last.request.headers["authorization"] == f"Bearer {CALLER_TOKEN}"

    async def test_nothing_else_is_given_the_token(self) -> None:
        """The SDK's bearer provider never consults the allowed-hosts validator itself, so this is
        all that stands between an off-Graph `@odata.nextLink` and a user's delegated credential."""
        provider = _CallerTokenProvider(CALLER_TOKEN)

        assert await provider.get_authorization_token("https://graph.microsoft.com/v1.0/me")
        assert await provider.get_authorization_token("https://example.invalid/v1.0/me") == ""

    async def test_the_right_host_over_the_wrong_scheme_is_given_nothing_either(self) -> None:
        """`AllowedHostsValidator` compares the hostname and nothing else, so a host check alone
        hands the delegated token to `http://graph.microsoft.com/...` in cleartext."""
        provider = _CallerTokenProvider(CALLER_TOKEN)

        assert await provider.get_authorization_token("http://graph.microsoft.com/v1.0/me") == ""
        assert await provider.get_authorization_token("ftp://graph.microsoft.com/v1.0/me") == ""
        assert await provider.get_authorization_token("//graph.microsoft.com/v1.0/me") == ""


class TestTheGraphBaseUrlIsSetInOnePlace:
    async def test_no_empty_path_segment_reaches_the_wire(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A second base_url produces `https://graph.microsoft.com/v1.0//me`: httpx normalises a
        base_url to end with a slash, `HttpxRequestAdapter` copies the transport's verbatim, and the
        SDK's URL templates join their own leading slash onto it. Graph tolerates the empty
        segment, so nothing fails loudly — hence the assertion on the built URL."""
        route = graph.get("/me").mock(return_value=httpx.Response(200, json={"id": "u-1"}))

        _ = await client.me.get()

        assert str(route.calls.last.request.url) == f"{GRAPH_V1}/me"

    async def test_the_adapter_holds_it_and_the_transport_does_not(
        self, transport: httpx.AsyncClient, client: GraphServiceClient
    ) -> None:
        """An unset transport base_url is what lets the adapter emit an absolute URL httpx never
        joins onto; the adapter's missing trailing slash keeps the join clean if it ever does."""
        # The ignore is for the SDK leaving `request_adapter`'s generic parameter unbound.
        base_url: str = client.request_adapter.base_url  # pyright: ignore[reportUnknownMemberType]

        assert str(transport.base_url) == ""
        assert base_url == GRAPH_V1
        assert not base_url.endswith("/")


class TestThrottling:
    async def test_retry_after_is_waited_out_and_the_call_then_succeeds(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        retry_sleeps: RecordedSleeps,
    ) -> None:
        """The factory installs no middleware on a client it is handed unless asked, and losing
        the retry handler shows up only as intermittent 429s reaching tools."""
        graph.get("/me").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "7"}),
                httpx.Response(200, json={"id": "u-1", "displayName": "Ada Lovelace"}),
            ]
        )

        user = await client.me.get()

        assert user is not None
        assert retry_sleeps.delays == [7], "the wait must be Graph's Retry-After, not a backoff"


class TestTheTransportRunsTheSdksOwnPipeline:
    async def test_it_is_the_sdks_default_chain_with_the_url_replacer_quietened(self) -> None:
        """`_graph_middleware` inlines `GraphClientFactory.create_with_default_middleware`, which
        builds and loads the handler list in one step with no seam to swap a handler into. The cost
        is that a handler the SDK adds in a later version would quietly not be installed."""
        options: dict[str, RequestOption] = {**sdk_middleware_options}
        sdk = GraphClientFactory.create_with_default_middleware(
            client=httpx.AsyncClient(), options=options
        )
        ours = create_graph_transport(GraphSettings())
        try:
            expected = [
                "_QuietUrlReplaceHandler" if name == "UrlReplaceHandler" else name
                for name in _handler_chain(sdk)
            ]
            assert expected, "the SDK's own chain came back empty, so this compares nothing"
            assert _handler_chain(ours) == expected
        finally:
            await sdk.aclose()
            await ours.aclose()


class TestANonIdempotentCallIsNotRetried:
    """`no_retry` exists because the SDK retries POST exactly as readily as GET, and Graph has no
    idempotency key for sending mail. The middleware default and the per-request override are
    asserted together: a test of the override alone would still pass if the default had changed to
    match it, and the whole point is that they differ."""

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_by_default_a_post_that_answers_503_is_sent_once_per_retry(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/me/sendMail").mock(return_value=httpx.Response(503))

        with pytest.raises(Exception):  # noqa: B017, PT011
            await client.me.send_mail.post(SendMailPostRequestBody())

        assert route.call_count == GraphSettings().max_retries + 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_the_override_sends_it_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/me/sendMail").mock(return_value=httpx.Response(503))

        with pytest.raises(Exception):  # noqa: B017, PT011
            await client.me.send_mail.post(
                SendMailPostRequestBody(),
                request_configuration=RequestConfiguration(options=no_retry()),
            )

        assert route.call_count == 1


class TestRequestWithQuery:
    """`request_with_query` is the only way a raw, untyped OData parameter (`pagelevel`,
    `includeIDs`, `sectionName`, …) reaches the wire: the SDK's typed query-parameter classes
    have no field for any of them, and setting one straight on `query_parameters` without first
    naming it in the url template's `{?…}` list is silently dropped."""

    def test_it_extends_an_existing_query_block_and_keeps_the_typed_params(
        self, client: GraphServiceClient
    ) -> None:
        pages = client.me.onenote.pages

        request = request_with_query(
            Method.GET, pages.url_template, pages.path_parameters, query={"pagelevel": "true"}
        )
        request.query_parameters["%24select"] = ["title", "id"]
        request.query_parameters["%24top"] = 5
        request.path_parameters["baseurl"] = GRAPH_V1

        url = str(request.url)
        assert url.startswith(f"{GRAPH_V1}/users/me-token-to-replace/onenote/pages?")
        assert "pagelevel=true" in url
        assert "%24select=title,id" in url
        assert "%24top=5" in url

    def test_it_appends_a_new_query_block_when_the_template_has_none(
        self, client: GraphServiceClient
    ) -> None:
        content = client.me.onenote.pages.by_onenote_page_id("abc").content

        request = request_with_query(
            Method.GET,
            content.url_template,
            content.path_parameters,
            query={"includeIDs": "true", "preAuthenticated": "true"},
        )
        request.path_parameters["baseurl"] = GRAPH_V1

        extended_template = request.url_template
        assert extended_template is not None
        assert extended_template.endswith("{?includeIDs,preAuthenticated}")
        url = str(request.url)
        assert "includeIDs=true" in url
        assert "preAuthenticated=true" in url

    def test_a_raw_name_already_in_the_template_is_not_duplicated(
        self, client: GraphServiceClient
    ) -> None:
        pages = client.me.onenote.pages
        once = request_with_query(
            Method.GET, pages.url_template, pages.path_parameters, query={"pagelevel": "true"}
        )
        once_template = once.url_template
        assert once_template is not None

        twice = request_with_query(
            Method.GET, once_template, pages.path_parameters, query={"pagelevel": "false"}
        )

        assert twice.url_template == once_template
        assert once_template.count("pagelevel") == 1

    def test_typed_parameters_reach_the_wire_alongside_a_raw_name(
        self, client: GraphServiceClient
    ) -> None:
        pages = client.me.onenote.pages
        typed = PagesRequestBuilder.PagesRequestBuilderGetQueryParameters(
            select=["id", "title"],
            expand=["parentNotebook"],
            top=5,
            filter="title eq 'x'",
            orderby=["lastModifiedDateTime desc"],
            skip=10,
        )

        request = request_with_query(
            Method.GET,
            pages.url_template,
            pages.path_parameters,
            query={"pagelevel": "true"},
            typed=typed,
        )
        request.path_parameters["baseurl"] = GRAPH_V1

        url = str(request.url)
        assert url.startswith(f"{GRAPH_V1}/users/me-token-to-replace/onenote/pages?")
        assert "pagelevel=true" in url
        assert "%24select=id,title" in url
        assert "%24expand=parentNotebook" in url
        assert "%24top=5" in url
        assert "%24filter=title%20eq%20%27x%27" in url
        assert "%24orderby=lastModifiedDateTime%20desc" in url
        assert "%24skip=10" in url

    def test_no_typed_parameters_means_no_odata_keys_on_the_wire(
        self, client: GraphServiceClient
    ) -> None:
        pages = client.me.onenote.pages

        request = request_with_query(
            Method.GET, pages.url_template, pages.path_parameters, query={"pagelevel": "true"}
        )
        request.path_parameters["baseurl"] = GRAPH_V1

        url = str(request.url)
        assert "pagelevel=true" in url
        assert "%24select" not in url

    def test_a_typed_odata_name_is_refused(self, client: GraphServiceClient) -> None:
        pages = client.me.onenote.pages

        with pytest.raises(AssertionError):
            request_with_query(
                Method.GET, pages.url_template, pages.path_parameters, query={"$select": "id"}
            )

        with pytest.raises(AssertionError):
            request_with_query(
                Method.GET, pages.url_template, pages.path_parameters, query={"%24select": "id"}
            )


class TestFetchResponse:
    """`fetch_response` is the only route to a Graph response's raw status, headers and bytes: the
    SDK's normal `.content.get()` deserialises straight to `bytes` and throws everything else away.
    """

    async def test_a_success_carries_the_status_bytes_and_the_content_type(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/onenote/resources/res-1/content").mock(
            return_value=httpx.Response(
                200, content=b"\x89PNG\r\n", headers={"Content-Type": "image/png; charset=binary"}
            )
        )

        fetched = await fetch_response(client, _resource_content_request(client, "res-1"))

        assert fetched.status_code == 200
        assert fetched.content == b"\x89PNG\r\n"
        assert fetched.media_type == "image/png"

    async def test_no_content_type_header_is_none(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/onenote/resources/res-1/content").mock(
            return_value=httpx.Response(200, content=b"body")
        )

        fetched = await fetch_response(client, _resource_content_request(client, "res-1"))

        assert fetched.media_type is None

    async def test_headers_come_back_lower_cased(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/onenote/resources/res-1/content").mock(
            return_value=httpx.Response(
                202, content=b"", headers={"Operation-Location": "https://graph.invalid/op/1"}
            )
        )

        fetched = await fetch_response(client, _resource_content_request(client, "res-1"))

        assert fetched.headers["operation-location"] == "https://graph.invalid/op/1"

    async def test_it_does_not_mutate_the_request_it_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/onenote/resources/res-1/content").mock(
            return_value=httpx.Response(200, content=b"body")
        )
        request = _resource_content_request(client, "res-1")
        before = dict(request.request_options)

        _ = await fetch_response(client, request)

        assert dict(request.request_options) == before

    async def test_a_request_missing_native_response_is_refused(
        self, client: GraphServiceClient
    ) -> None:
        request = _resource_content_request(client, "res-1", native=False)

        with pytest.raises(AssertionError):
            await fetch_response(client, request)

    async def test_a_404_error_body_raises_an_error_this_package_can_classify(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/onenote/resources/res-1/content").mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound), graph_errors("test_fetch_response"):
            await fetch_response(client, _resource_content_request(client, "res-1"))

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_429_with_retry_after_is_classified_as_throttled(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/onenote/resources/res-1/content").mock(
            return_value=httpx.Response(
                429,
                headers={"Retry-After": "12"},
                json={"error": {"code": "TooManyRequests", "message": "throttled"}},
            )
        )

        with pytest.raises(GraphThrottled) as excinfo, graph_errors("test_fetch_response"):
            await fetch_response(client, _resource_content_request(client, "res-1"))
        assert excinfo.value.retry_after_seconds == 12
