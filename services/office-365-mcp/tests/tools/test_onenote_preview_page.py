import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import OnenotePageHandle, OnenoteSectionHandle
from office_365_mcp.tools import onenote_preview_page as previewer

PAGE_ID = "0-SYNTHETICPAGE0000!0001"
SECTION_ID = "0-SYNTHETICSECTION00!0001"

_PREVIEW_PATH = "/me/onenote/pages/0-SYNTHETICPAGE0000%210001/preview()"

_PAGE = OnenotePageHandle(PAGE_ID).uri
_SECTION = OnenoteSectionHandle(SECTION_ID).uri

_IMAGE_URL = "https://graph.microsoft.com/v1.0/me/onenote/resources/res-1/content"


def _preview_payload(
    *,
    preview_text: str | None = "This week's roadmap notes",
    image_href: str | None = _IMAGE_URL,
) -> dict[str, object]:
    payload: dict[str, object] = {"previewText": preview_text}
    payload["links"] = {"previewImageUrl": {"href": image_href}} if image_href is not None else None
    return payload


@pytest.fixture
def preview(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_PREVIEW_PATH).mock(return_value=httpx.Response(200, json=_preview_payload()))


async def _preview(client: GraphServiceClient, *, page: str = _PAGE) -> previewer.PagePreview:
    return await previewer.preview_page(client, page=page)


class TestWhatItAsks:
    async def test_it_reads_the_preview_of_the_right_page_by_its_percent_encoded_id(
        self, client: GraphServiceClient, preview: respx.Route
    ) -> None:
        _ = await _preview(client)

        assert preview.call_count == 1
        assert b"%21" in preview.calls.last.request.url.raw_path

    async def test_the_preview_request_carries_no_query_parameters(
        self, client: GraphServiceClient, preview: respx.Route
    ) -> None:
        _ = await _preview(client)

        assert preview.calls.last.request.url.params == httpx.QueryParams()


class TestWhatItAnswers:
    async def test_the_page_uri_is_echoed_from_the_argument(
        self, client: GraphServiceClient, preview: respx.Route
    ) -> None:
        answer = await _preview(client)

        assert answer.page_uri == OnenotePageHandle(PAGE_ID).uri
        assert preview.call_count == 1

    @pytest.mark.usefixtures("preview")
    async def test_the_text_and_image_address_are_mapped_from_graph(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _preview(client)

        assert answer.preview_text == "This week's roadmap notes"
        assert answer.preview_image_url == _IMAGE_URL

    async def test_no_preview_text_answers_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PREVIEW_PATH).mock(
            return_value=httpx.Response(200, json=_preview_payload(preview_text=None))
        )

        answer = await _preview(client)

        assert answer.preview_text is None

    async def test_no_links_at_all_answers_a_null_image_address(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PREVIEW_PATH).mock(
            return_value=httpx.Response(200, json={"previewText": "hi", "links": None})
        )

        answer = await _preview(client)

        assert answer.preview_image_url is None

    async def test_links_with_no_preview_image_url_answers_a_null_image_address(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PREVIEW_PATH).mock(
            return_value=httpx.Response(
                200, json={"previewText": "hi", "links": {"previewImageUrl": None}}
            )
        )

        answer = await _preview(client)

        assert answer.preview_image_url is None


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            _SECTION,
            PAGE_ID,
            "https://onenote.example.invalid/pages/sprint-notes",
            "Sprint notes",
            "onenote:///pages/",
        ],
    )
    async def test_a_value_that_is_not_a_page_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_pages"):
            _ = await _preview(client, page=value)

        assert graph.calls.call_count == 0

    async def test_the_refusal_names_the_page_handle_shape(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match=r"onenote:///pages/\{id\}") as refused:
            _ = await _preview(client, page=_SECTION)

        assert "onenote:///sections/{id}" in str(refused.value)


class TestGraphFailures:
    async def test_a_404_on_the_preview_is_a_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PREVIEW_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _preview(client)

    async def test_a_403_on_the_preview_is_a_graph_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PREVIEW_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "Forbidden"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _preview(client)
