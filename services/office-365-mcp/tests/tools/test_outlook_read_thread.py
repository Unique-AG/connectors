"""Every response body here is synthesised. None came from a real mailbox."""

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import MailMessageHandle, mail_message_handle
from office_365_mcp.tools.outlook_read_thread import MAX_MESSAGES, read_thread

_ANCHOR_ID = "AAMkAGI2SYNTHETIC-anchor-0001="
_OLDER_ID = "AAMkAGI2SYNTHETIC-older-0002="
_CONVERSATION = "AAQkADAwATNiZmYAZS1SYNTHETIC-conversation"
_OTHER_CONVERSATION = "AAQkADAwATNiZmYAZS1SYNTHETIC-elsewhere"

_HANDLE = MailMessageHandle(_ANCHOR_ID)


def _message(
    message_id: str, *, conversation: str = _CONVERSATION, received: str = "2026-03-04T09:15:00Z"
) -> dict[str, object]:
    return {
        "id": message_id,
        "conversationId": conversation,
        "subject": "Contract review",
        "bodyPreview": "Thanks, agreed.",
        "from": {"emailAddress": {"name": "Legal", "address": "legal@contoso.invalid"}},
        "toRecipients": [{"emailAddress": {"name": "Ada", "address": "ada@contoso.invalid"}}],
        "receivedDateTime": received,
        "isRead": True,
        "hasAttachments": False,
        "parentFolderId": "AQMkADAwSYNTHETIC-folder",
        "webLink": "https://outlook.office365.invalid/owa/?ItemID=synthetic",
    }


@pytest.fixture
def anchor(graph: respx.MockRouter) -> respx.Route:
    return graph.get(f"/me/messages/{_ANCHOR_ID}")


@pytest.fixture
def thread(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me/messages")


def _page(messages: list[dict[str, object]], *, more: bool = False) -> dict[str, object]:
    page: dict[str, object] = {"value": messages}
    if more:
        page["@odata.nextLink"] = "https://graph.microsoft.com/v1.0/me/messages?%24skip=100"
    return page


def _anchor_body(conversation: str | None = _CONVERSATION) -> dict[str, object]:
    return {"id": _ANCHOR_ID, "conversationId": conversation}


class TestWhatItAsksGraphFor:
    async def test_it_reads_the_conversation_off_the_anchor_first(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json={"value": [_message(_ANCHOR_ID)]}))

        await read_thread(client, handle=_HANDLE)

        assert anchor.call_count == 1
        assert "conversationId" in anchor.calls.last.request.url.params["$select"]

    async def test_it_filters_on_the_conversation_the_anchor_named(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json={"value": [_message(_ANCHOR_ID)]}))

        await read_thread(client, handle=_HANDLE)

        assert thread.calls.last.request.url.params["$filter"] == (
            f"conversationId eq '{_CONVERSATION}'"
        )

    async def test_it_sends_no_order_because_graph_refuses_one_beside_that_filter(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        """Every property in `$orderby` must also be in `$filter`, so an order on receipt time
        beside a filter on conversation answers `InefficientFilter`."""
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json={"value": [_message(_ANCHOR_ID)]}))

        await read_thread(client, handle=_HANDLE)

        assert "$orderby" not in thread.calls.last.request.url.params

    async def test_both_requests_declare_the_immutable_id_space(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        """The handle carries an immutable id, and Graph reads a path id in whichever space the
        request declares."""
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json={"value": [_message(_ANCHOR_ID)]}))

        await read_thread(client, handle=_HANDLE)

        assert 'IdType="ImmutableId"' in anchor.calls.last.request.headers["Prefer"]
        assert 'IdType="ImmutableId"' in thread.calls.last.request.headers["Prefer"]

    async def test_a_quote_in_a_conversation_id_cannot_end_the_odata_literal(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        awkward = "AAQk'injected"
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body(awkward)))
        thread.mock(
            return_value=httpx.Response(
                200, json={"value": [_message(_ANCHOR_ID, conversation=awkward)]}
            )
        )

        await read_thread(client, handle=_HANDLE)

        assert thread.calls.last.request.url.params["$filter"] == (
            "conversationId eq 'AAQk''injected'"
        )


class TestItChecksThatGraphAppliedTheFilter:
    """`$filter=conversationId` is in no Microsoft document, and Graph ignores an unsupported
    filter rather than refusing it. So the answer is checked instead of trusted."""

    async def test_a_foreign_conversation_in_the_answer_is_refused(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _message(_ANCHOR_ID),
                        _message(_OLDER_ID, conversation=_OTHER_CONVERSATION),
                    ]
                },
            )
        )

        with pytest.raises(ToolError, match="did not apply the filter"):
            await read_thread(client, handle=_HANDLE)

    async def test_an_answer_without_the_anchor_is_refused_even_when_it_all_matches(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        """What a filter applied to the wrong value looks like: every row agrees with every other
        row, and none of them is the message the caller named."""
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json={"value": [_message(_OLDER_ID)]}))

        with pytest.raises(ToolError, match="did not apply the filter"):
            await read_thread(client, handle=_HANDLE)

    async def test_an_empty_answer_is_not_treated_as_a_failed_filter(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        """A mailbox that kept no copy of the thread is a real answer, and an empty page carries no
        evidence either way."""
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json={"value": []}))

        result = await read_thread(client, handle=_HANDLE)

        assert result.messages == []
        assert result.message_count == 0


class TestWhatItAnswers:
    async def test_the_messages_come_back_oldest_first(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _message(_ANCHOR_ID, received="2026-03-05T09:00:00Z"),
                        _message(_OLDER_ID, received="2026-03-01T08:00:00Z"),
                    ]
                },
            )
        )

        result = await read_thread(client, handle=_HANDLE)

        assert [message.uri for message in result.messages] == [
            MailMessageHandle(_OLDER_ID).uri,
            MailMessageHandle(_ANCHOR_ID).uri,
        ]

    async def test_a_message_with_no_received_time_does_not_break_the_order(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        """A draft in the thread was never received."""
        draft = _message(_OLDER_ID)
        del draft["receivedDateTime"]
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json={"value": [_message(_ANCHOR_ID), draft]}))

        result = await read_thread(client, handle=_HANDLE)

        assert result.message_count == 2

    async def test_it_names_the_mailboxes_it_did_not_search(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json={"value": [_message(_ANCHOR_ID)]}))

        result = await read_thread(client, handle=_HANDLE)

        assert "archive" in result.searched_scope
        assert "delegated" in result.searched_scope

    async def test_a_thread_graph_had_more_of_says_it_is_incomplete(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        """Graph's own next link, not a full window: a page can come back short of `$top` and
        still carry one, because `$skip` counts every item the service walked."""
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json=_page([_message(_ANCHOR_ID)], more=True)))

        result = await read_thread(client, handle=_HANDLE)

        assert result.complete is False

    async def test_a_thread_longer_than_one_page_answers_without_the_anchor_on_it(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        """The anchor check cannot run on a truncated page. There is no `$orderby` to say which
        messages the page holds, so a long thread can leave the anchor off it honestly — and
        refusing there would blame Graph for a filter it did apply."""
        crowd = [_message(f"{_OLDER_ID}{index}") for index in range(MAX_MESSAGES)]
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json=_page(crowd, more=True)))

        result = await read_thread(client, handle=_HANDLE)

        assert result.message_count == MAX_MESSAGES
        assert result.complete is False

    async def test_a_foreign_conversation_is_refused_even_on_a_truncated_page(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        """The half of the check that survives truncation. A row from another conversation proves
        the filter was dropped whatever the page size."""
        crowd = [_message(f"{_OLDER_ID}{index}") for index in range(MAX_MESSAGES - 1)]
        crowd.append(_message(_OLDER_ID, conversation=_OTHER_CONVERSATION))
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body()))
        thread.mock(return_value=httpx.Response(200, json=_page(crowd, more=True)))

        with pytest.raises(ToolError, match="did not apply the filter"):
            await read_thread(client, handle=_HANDLE)

    async def test_an_anchor_with_no_conversation_answers_nothing_rather_than_everything(
        self, client: GraphServiceClient, anchor: respx.Route, thread: respx.Route
    ) -> None:
        """A filter built from a null conversation would have matched the whole mailbox."""
        anchor.mock(return_value=httpx.Response(200, json=_anchor_body(None)))

        result = await read_thread(client, handle=_HANDLE)

        assert result.messages == []
        assert thread.call_count == 0


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "uri",
        [
            "outlook:///folders/AQMkADAw",
            "outlook:///drafts/AAMkAGI2",
            "teams:///chats/19%3Ax%40thread.v2/messages/1770000000000",
            "",
        ],
    )
    def test_a_uri_that_is_not_a_message_handle_never_becomes_one(self, uri: str) -> None:
        assert mail_message_handle(uri) is None

    async def test_a_message_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, anchor: respx.Route
    ) -> None:
        anchor.mock(return_value=httpx.Response(404))

        with pytest.raises(GraphNotFound):
            await read_thread(client, handle=_HANDLE)

    async def test_a_refused_read_is_a_forbidden(
        self, client: GraphServiceClient, anchor: respx.Route
    ) -> None:
        anchor.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            await read_thread(client, handle=_HANDLE)
