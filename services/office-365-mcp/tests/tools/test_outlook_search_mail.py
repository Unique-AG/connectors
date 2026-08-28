"""Every response body here is synthesised. None came from a real mailbox."""

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphThrottled
from office_365_mcp.shared.handles import MailMessageHandle
from office_365_mcp.tools.outlook_search_mail import (
    MAX_RESULTS,
    SearchCriteria,
    search_mail,
)

_REST_ID = "AAMkAGI2SYNTHETIC-rest-0001="
_STABLE_ID = "AAMkAGI2SYNTHETIC-immutable-0001="
_SECOND_REST_ID = "AAMkAGI2SYNTHETIC-rest-0002="
_SECOND_STABLE_ID = "AAMkAGI2SYNTHETIC-immutable-0002="


def _message(message_id: str, *, subject: str = "Invoice 4471") -> dict[str, object]:
    return {
        "id": message_id,
        "subject": subject,
        "bodyPreview": "Please find the invoice attached.",
        "from": {"emailAddress": {"name": "Bob Vance", "address": "bob@vance.invalid"}},
        "toRecipients": [{"emailAddress": {"name": "Ada", "address": "ada@contoso.invalid"}}],
        "receivedDateTime": "2026-03-04T09:15:00Z",
        "isRead": False,
        "hasAttachments": True,
        "parentFolderId": "AQMkADAwSYNTHETIC-folder",
        "webLink": "https://outlook.office365.invalid/owa/?ItemID=synthetic",
    }


def _translation(pairs: dict[str, str]) -> dict[str, object]:
    return {"value": [{"sourceId": source, "targetId": target} for source, target in pairs.items()]}


@pytest.fixture
def searched(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me/messages")


@pytest.fixture
def translated(graph: respx.MockRouter) -> respx.Route:
    return graph.post("/me/translateExchangeIds")


class TestWhatItAsksGraphFor:
    async def test_it_sends_the_criteria_as_one_quoted_kql_string(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client, SearchCriteria(query="invoice", sender="bob@vance.invalid"), limit=25
        )

        search = searched.calls.last.request.url.params["$search"]
        assert search == '"invoice from:bob@vance.invalid"'

    async def test_it_asks_for_the_shared_summary_fields_and_the_callers_window(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(query="invoice"), limit=7)

        params = searched.calls.last.request.url.params
        assert params["$top"] == "7"
        assert "bodyPreview" in params["$select"]

    async def test_it_never_sends_an_order_or_a_filter_beside_the_search(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        """Graph fails an unsupported combination silently, so an ignored `$orderby` would return
        its own order under a label promising another."""
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        params = searched.calls.last.request.url.params
        assert "$orderby" not in params
        assert "$filter" not in params

    async def test_it_does_not_ask_for_immutable_ids_on_the_search_itself(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        """The header is not honoured under `$search` and Graph answers `Preference-Applied`
        regardless, so sending it would buy a false confirmation and nothing else."""
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        assert "ImmutableId" not in searched.calls.last.request.headers.get("Prefer", "")


class TestTheHandlesItMints:
    async def test_a_hit_carries_the_translated_id_and_never_the_searched_one(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": [_message(_REST_ID)]}))
        translated.mock(return_value=httpx.Response(200, json=_translation({_REST_ID: _STABLE_ID})))

        results = await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        assert [hit.uri for hit in results.messages] == [MailMessageHandle(_STABLE_ID).uri]

    async def test_it_asks_the_exchange_for_every_hit_in_one_call(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(
            return_value=httpx.Response(
                200, json={"value": [_message(_REST_ID), _message(_SECOND_REST_ID)]}
            )
        )
        translated.mock(
            return_value=httpx.Response(
                200,
                json=_translation({_REST_ID: _STABLE_ID, _SECOND_REST_ID: _SECOND_STABLE_ID}),
            )
        )

        results = await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        assert translated.call_count == 1
        assert len(results.messages) == 2

    async def test_a_hit_the_exchange_could_not_translate_is_dropped(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        """A handle that resolves now and 404s once Outlook files the message is the failure the
        exchange exists to prevent, and a model reads that 404 as "deleted"."""
        searched.mock(
            return_value=httpx.Response(
                200, json={"value": [_message(_REST_ID), _message(_SECOND_REST_ID)]}
            )
        )
        translated.mock(return_value=httpx.Response(200, json=_translation({_REST_ID: _STABLE_ID})))

        results = await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        assert [hit.uri for hit in results.messages] == [MailMessageHandle(_STABLE_ID).uri]

    async def test_an_empty_result_asks_the_exchange_nothing(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))

        results = await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        assert results.messages == []
        assert translated.call_count == 0


class TestWhatItAnswers:
    async def test_it_reports_the_fields_a_model_chooses_from(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": [_message(_REST_ID)]}))
        translated.mock(return_value=httpx.Response(200, json=_translation({_REST_ID: _STABLE_ID})))

        hit = (await search_mail(client, SearchCriteria(query="invoice"), limit=25)).messages[0]

        assert hit.subject == "Invoice 4471"
        assert hit.preview == "Please find the invoice attached."
        assert hit.sender is not None
        assert hit.sender.address == "bob@vance.invalid"
        assert [address.address for address in hit.to] == ["ada@contoso.invalid"]
        assert hit.received_at is not None
        assert hit.is_read is False
        assert hit.has_attachments is True
        assert hit.web_link == "https://outlook.office365.invalid/owa/?ItemID=synthetic"

    async def test_a_full_window_says_more_may_exist(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": [_message(_REST_ID)]}))
        translated.mock(return_value=httpx.Response(200, json=_translation({_REST_ID: _STABLE_ID})))

        results = await search_mail(client, SearchCriteria(query="invoice"), limit=1)

        assert results.more_may_exist is True

    async def test_a_short_answer_does_not(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": [_message(_REST_ID)]}))
        translated.mock(return_value=httpx.Response(200, json=_translation({_REST_ID: _STABLE_ID})))

        results = await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        assert results.more_may_exist is False


class TestWhatItRefuses:
    async def test_no_criterion_is_refused_before_graph_is_called(
        self, client: GraphServiceClient, searched: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="at least one of"):
            await search_mail(client, SearchCriteria(), limit=25)

        assert searched.call_count == 0

    async def test_a_query_of_nothing_but_punctuation_is_no_criterion(
        self, client: GraphServiceClient, searched: respx.Route
    ) -> None:
        """The KQL, not the arguments, is the honest test: a query that contributes no term would
        otherwise reach Graph as a criteria-free search."""
        with pytest.raises(ToolError, match="at least one of"):
            await search_mail(client, SearchCriteria(query="   "), limit=25)

        assert searched.call_count == 0

    @pytest.mark.parametrize("limit", [0, MAX_RESULTS + 1])
    async def test_a_window_outside_the_schema_is_an_assertion(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            await search_mail(client, SearchCriteria(query="invoice"), limit=limit)


class TestWhatAGraphFailureBecomes:
    async def test_a_refused_search_is_a_forbidden(
        self, client: GraphServiceClient, searched: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            await search_mail(client, SearchCriteria(query="invoice"), limit=25)

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_exchange_is_a_throttling_and_not_an_outage(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": [_message(_REST_ID)]}))
        translated.mock(return_value=httpx.Response(429, headers={"Retry-After": "12"}))

        with pytest.raises(GraphThrottled):
            await search_mail(client, SearchCriteria(query="invoice"), limit=25)
