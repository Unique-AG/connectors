import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphThrottled
from office_365_mcp.shared.handles import MailMessageHandle
from office_365_mcp.shared.mail import SUMMARY_FIELDS, MailFlag, MailImportance
from office_365_mcp.tools import outlook_search_mail as searcher
from office_365_mcp.tools.outlook_search_mail import (
    CRITERIA,
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


def _rest_id(number: int) -> str:
    return f"AAMkAGI2SYNTHETIC-rest-{number:04d}="


def _stable_id(number: int) -> str:
    return f"AAMkAGI2SYNTHETIC-immutable-{number:04d}="


def _hit(number: int, **fields: object) -> dict[str, object]:
    return _message(_rest_id(number)) | fields


def _translation_of(*numbers: int) -> dict[str, object]:
    return _translation({_rest_id(number): _stable_id(number) for number in numbers})


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

    async def test_a_multi_word_value_does_not_close_the_search_string_early(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(sender="Bob Vance"), limit=25)

        assert searched.calls.last.request.url.params["$search"] == '"from:\\"Bob Vance\\""'

    async def test_a_quote_a_caller_typed_cannot_end_the_search_string(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(subject='say "hello"'), limit=25)

        sent = searched.calls.last.request.url.params["$search"]
        assert sent.count('"') % 2 == 0

    async def test_the_to_line_and_the_wider_participants_are_different_terms(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(to="ada@contoso.invalid"), limit=25)
        assert searched.calls.last.request.url.params["$search"] == '"to:ada@contoso.invalid"'

        await search_mail(client, SearchCriteria(recipient="ada@contoso.invalid"), limit=25)
        assert (
            searched.calls.last.request.url.params["$search"]
            == '"participants:ada@contoso.invalid"'
        )

    async def test_an_attachment_name_is_sent_as_microsofts_own_property(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(attachment_name="api-catalog.md"), limit=25)

        assert searched.calls.last.request.url.params["$search"] == '"attachment:api-catalog.md"'

    async def test_a_file_name_with_a_space_stays_one_phrase(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(attachment_name="Q3 report.xlsx"), limit=25)

        sent = searched.calls.last.request.url.params["$search"]
        assert sent == '"attachment:\\"Q3 report.xlsx\\""'
        assert sent.count('"') % 2 == 0

    async def test_a_wildcard_in_a_file_name_is_sent_as_text_and_not_as_syntax(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(attachment_name="budget*"), limit=25)

        assert searched.calls.last.request.url.params["$search"] == '"attachment:\\"budget*\\""'

    async def test_every_criterion_is_anded_into_the_one_search_string(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(
                query="invoice",
                sender="bob@vance.invalid",
                recipient="dana@contoso.invalid",
                to="ada@contoso.invalid",
                subject="Q3",
                attachment_name="api-catalog.md",
            ),
            limit=25,
        )

        params = searched.calls.last.request.url.params
        assert params["$search"] == (
            '"invoice from:bob@vance.invalid participants:dana@contoso.invalid '
            + 'to:ada@contoso.invalid subject:Q3 attachment:api-catalog.md"'
        )
        assert "$filter" not in params

    async def test_it_asks_for_the_shared_summary_fields_and_the_callers_window(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(query="invoice"), limit=7)

        params = searched.calls.last.request.url.params
        assert params["$top"] == "7"
        assert "bodyPreview" in params["$select"]

    async def test_it_selects_every_shared_summary_field_and_never_the_headers(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        selected = searched.calls.last.request.url.params["$select"].split(",")
        assert [field for field in SUMMARY_FIELDS if field not in selected] == []
        assert "internetMessageHeaders" not in selected

    async def test_it_never_sends_an_order_or_a_filter_beside_the_search(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        params = searched.calls.last.request.url.params
        assert "$orderby" not in params
        assert "$filter" not in params

    async def test_it_does_not_ask_for_immutable_ids_on_the_search_itself(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        assert "ImmutableId" not in searched.calls.last.request.headers.get("Prefer", "")


class TestTheNarrowingTermsItSends:
    @pytest.mark.parametrize(
        ("importance", "term"),
        [
            ("low", "importance:low"),
            ("normal", "importance:medium"),
            ("high", "importance:high"),
        ],
    )
    async def test_importance_is_sent_with_the_value_names_microsoft_lists_for_search(
        self,
        client: GraphServiceClient,
        searched: respx.Route,
        translated: respx.Route,
        importance: MailImportance,
        term: str,
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(query="invoice"), importance=importance, limit=25)

        assert searched.calls.last.request.url.params["$search"] == f'"invoice AND {term}"'

    async def test_the_window_comes_first_then_the_importance_term(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(query="invoice", sender="bob@vance.invalid"),
            received_after=date(2026, 9, 1),
            received_before=date(2026, 9, 30),
            importance="high",
            limit=25,
        )

        params = searched.calls.last.request.url.params
        assert params["$search"] == (
            '"invoice from:bob@vance.invalid AND received>=2026-09-01T00:00:00Z '
            + 'AND received<2026-10-01T00:00:00Z AND importance:high"'
        )
        assert "$filter" not in params

    async def test_a_quoted_criterion_stays_escaped_beside_the_importance_term(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(sender="Bob Vance"), importance="low", limit=25)

        sent = searched.calls.last.request.url.params["$search"]
        assert sent == '"from:\\"Bob Vance\\" AND importance:low"'

    async def test_flagged_has_attachments_and_category_add_no_term_to_the_search(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(query="invoice"),
            flagged=True,
            has_attachments=True,
            category="Invoices",
            limit=25,
        )

        params = searched.calls.last.request.url.params
        assert params["$search"] == '"invoice"'
        assert "hasattachment" not in params["$search"].casefold()
        assert "$filter" not in params


class TestTheNarrowingItAppliesToThePage:
    @pytest.mark.parametrize(("flagged", "kept"), [(True, [1]), (False, [2, 3])])
    async def test_flagged_keeps_the_mail_by_follow_up_status_and_no_flag_matches_neither(
        self,
        client: GraphServiceClient,
        searched: respx.Route,
        translated: respx.Route,
        flagged: bool,
        kept: list[int],
    ) -> None:
        searched.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _hit(1, flag={"flagStatus": "flagged"}),
                        _hit(2, flag={"flagStatus": "notFlagged"}),
                        _hit(3, flag={"flagStatus": "complete"}),
                        _hit(4),
                    ]
                },
            )
        )
        translated.mock(return_value=httpx.Response(200, json=_translation_of(1, 2, 3, 4)))

        results = await search_mail(
            client, SearchCriteria(query="invoice"), flagged=flagged, limit=25
        )

        assert [hit.uri for hit in results.messages] == [
            MailMessageHandle(_stable_id(number)).uri for number in kept
        ]

    @pytest.mark.parametrize(("has_attachments", "kept"), [(True, [1]), (False, [2])])
    async def test_has_attachments_keeps_the_mail_by_attachment_state_and_a_null_matches_neither(
        self,
        client: GraphServiceClient,
        searched: respx.Route,
        translated: respx.Route,
        has_attachments: bool,
        kept: list[int],
    ) -> None:
        searched.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _hit(1, hasAttachments=True),
                        _hit(2, hasAttachments=False),
                        _hit(3, hasAttachments=None),
                    ]
                },
            )
        )
        translated.mock(return_value=httpx.Response(200, json=_translation_of(1, 2, 3)))

        results = await search_mail(
            client, SearchCriteria(query="invoice"), has_attachments=has_attachments, limit=25
        )

        assert [hit.uri for hit in results.messages] == [
            MailMessageHandle(_stable_id(number)).uri for number in kept
        ]

    async def test_a_category_matches_the_whole_name_and_ignores_case(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _hit(1, categories=["Invoices"]),
                        _hit(2, categories=["Red category", "invoices"]),
                        _hit(3, categories=["Invoices 2025"]),
                        _hit(4),
                    ]
                },
            )
        )
        translated.mock(return_value=httpx.Response(200, json=_translation_of(1, 2, 3, 4)))

        results = await search_mail(
            client, SearchCriteria(query="invoice"), category="INVOICES", limit=25
        )

        assert [hit.uri for hit in results.messages] == [
            MailMessageHandle(_stable_id(1)).uri,
            MailMessageHandle(_stable_id(2)).uri,
        ]

    async def test_flagged_and_category_must_both_pass(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        flag = {"flagStatus": "flagged"}
        searched.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _hit(1, flag=flag, categories=["Invoices"]),
                        _hit(2, flag=flag, categories=["Receipts"]),
                        _hit(3, flag={"flagStatus": "notFlagged"}, categories=["Invoices"]),
                    ]
                },
            )
        )
        translated.mock(return_value=httpx.Response(200, json=_translation_of(1, 2, 3)))

        results = await search_mail(
            client,
            SearchCriteria(query="invoice"),
            flagged=True,
            category="Invoices",
            limit=25,
        )

        assert [hit.uri for hit in results.messages] == [MailMessageHandle(_stable_id(1)).uri]

    async def test_the_exchange_is_asked_to_translate_only_the_mail_that_stays(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _hit(1, categories=["Invoices"]),
                        _hit(2, categories=["Receipts"]),
                    ]
                },
            )
        )
        translated.mock(return_value=httpx.Response(200, json=_translation_of(1)))

        await search_mail(client, SearchCriteria(query="invoice"), category="Invoices", limit=25)

        asked = cast("dict[str, list[str]]", json.loads(translated.calls.last.request.content))
        assert asked["InputIds"] == [_rest_id(1)]

    async def test_a_full_page_the_filter_empties_still_says_more_may_exist(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _hit(1, flag={"flagStatus": "notFlagged"}),
                        _hit(2, flag={"flagStatus": "notFlagged"}),
                    ]
                },
            )
        )

        results = await search_mail(client, SearchCriteria(query="invoice"), flagged=True, limit=2)

        assert results.messages == []
        assert results.more_may_exist is True
        assert translated.call_count == 0

    async def test_a_short_page_the_filter_empties_says_nothing_more_exists(
        self, client: GraphServiceClient, searched: respx.Route
    ) -> None:
        searched.mock(
            return_value=httpx.Response(
                200, json={"value": [_hit(1, flag={"flagStatus": "notFlagged"})]}
            )
        )

        results = await search_mail(client, SearchCriteria(query="invoice"), flagged=True, limit=25)

        assert results.messages == []
        assert results.more_may_exist is False


class TestTheWindowItSends:
    async def test_a_lower_bound_reaches_graph_as_a_comparison_beside_the_criteria(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client, SearchCriteria(query="invoice"), received_after=date(2026, 9, 1), limit=25
        )

        assert (
            searched.calls.last.request.url.params["$search"]
            == '"invoice AND received>=2026-09-01T00:00:00Z"'
        )

    async def test_a_bare_date_upper_bound_closes_at_the_start_of_the_following_day(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client, SearchCriteria(subject="invoice"), received_before=date(2026, 9, 30), limit=25
        )

        assert (
            searched.calls.last.request.url.params["$search"]
            == '"subject:invoice AND received<2026-10-01T00:00:00Z"'
        ), "an upper bound on the named day's own midnight drops the whole day it names"

    async def test_a_moment_upper_bound_closes_at_the_second_it_names(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(query="invoice"),
            received_before=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            limit=25,
        )

        assert (
            searched.calls.last.request.url.params["$search"]
            == '"invoice AND received<=2026-09-08T12:00:00Z"'
        )

    async def test_a_two_sided_window_sends_both_comparisons_and_still_no_filter(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(subject="invoice"),
            received_after=date(2026, 9, 1),
            received_before=date(2026, 9, 30),
            limit=25,
        )

        params = searched.calls.last.request.url.params
        assert params["$search"] == (
            '"subject:invoice AND received>=2026-09-01T00:00:00Z AND received<2026-10-01T00:00:00Z"'
        )
        assert "$filter" not in params

    async def test_one_date_in_both_bounds_searches_that_single_day(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(query="invoice"),
            received_after=date(2026, 9, 8),
            received_before=date(2026, 9, 8),
            limit=25,
        )

        assert searched.calls.last.request.url.params["$search"] == (
            '"invoice AND received>=2026-09-08T00:00:00Z AND received<2026-09-09T00:00:00Z"'
        )

    async def test_a_date_and_a_moment_can_bound_the_same_window(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(query="invoice"),
            received_after=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            received_before=date(2026, 9, 30),
            limit=25,
        )

        assert searched.calls.last.request.url.params["$search"] == (
            '"invoice AND received>=2026-09-08T12:00:00Z AND received<2026-10-01T00:00:00Z"'
        )

    async def test_a_moment_with_no_zone_is_read_as_utc_and_not_as_the_servers_own(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(query="invoice"),
            received_after=datetime(2026, 9, 8, 12, 0),
            limit=25,
        )

        assert (
            searched.calls.last.request.url.params["$search"]
            == '"invoice AND received>=2026-09-08T12:00:00Z"'
        )

    async def test_a_moment_east_of_utc_is_converted_rather_than_relabelled(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(query="invoice"),
            received_after=datetime(2026, 9, 8, 14, 0, tzinfo=timezone(timedelta(hours=2))),
            limit=25,
        )

        assert (
            searched.calls.last.request.url.params["$search"]
            == '"invoice AND received>=2026-09-08T12:00:00Z"'
        )

    async def test_a_sub_second_bound_keeps_its_precision_on_the_wire(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            SearchCriteria(query="invoice"),
            received_after=datetime(2026, 9, 8, 12, 0, 0, 500000, tzinfo=UTC),
            received_before=datetime(2026, 9, 8, 17, 0, 0, 750000, tzinfo=UTC),
            limit=25,
        )

        assert searched.calls.last.request.url.params["$search"] == (
            '"invoice AND received>=2026-09-08T12:00:00.500000Z '
            + 'AND received<=2026-09-08T17:00:00.750000Z"'
        )

    @pytest.mark.parametrize(
        ("criteria", "term"),
        [
            (SearchCriteria(query="invoice"), "invoice"),
            (SearchCriteria(sender="bob@vance.invalid"), "from:bob@vance.invalid"),
            (
                SearchCriteria(recipient="dana@contoso.invalid"),
                "participants:dana@contoso.invalid",
            ),
            (SearchCriteria(to="ada@contoso.invalid"), "to:ada@contoso.invalid"),
            (SearchCriteria(subject="Q3"), "subject:Q3"),
            (SearchCriteria(attachment_name="api-catalog.md"), "attachment:api-catalog.md"),
        ],
    )
    async def test_the_window_narrows_every_criterion_and_stands_in_for_none_of_them(
        self,
        client: GraphServiceClient,
        searched: respx.Route,
        translated: respx.Route,
        criteria: SearchCriteria,
        term: str,
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(
            client,
            criteria,
            received_after=date(2026, 9, 1),
            received_before=date(2026, 9, 30),
            limit=25,
        )

        assert searched.calls.last.request.url.params["$search"] == (
            f'"{term} AND received>=2026-09-01T00:00:00Z AND received<2026-10-01T00:00:00Z"'
        )


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

    async def test_it_reports_importance_flag_categories_draft_state_and_reply_to(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        hit = _message(_REST_ID) | {
            "importance": "high",
            "flag": {"flagStatus": "notFlagged"},
            "categories": ["Invoices", "Red category"],
            "isDraft": False,
            "sender": {"emailAddress": {"name": "Sam Assistant", "address": "sam@vance.invalid"}},
            "replyTo": [{"emailAddress": {"name": "Billing", "address": "billing@vance.invalid"}}],
        }
        searched.mock(return_value=httpx.Response(200, json={"value": [hit]}))
        translated.mock(return_value=httpx.Response(200, json=_translation({_REST_ID: _STABLE_ID})))

        row = (await search_mail(client, SearchCriteria(query="invoice"), limit=25)).messages[0]

        assert row.importance == "high"
        assert row.flag == MailFlag(status="notFlagged", start=None, due=None, completed=None)
        assert row.categories == ["Invoices", "Red category"]
        assert row.is_draft is False
        assert row.sent_by is not None
        assert row.sent_by.address == "sam@vance.invalid"
        assert [address.address for address in row.reply_to] == ["billing@vance.invalid"]

    async def test_a_hit_with_none_of_those_fields_answers_null_and_empty(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": [_message(_REST_ID)]}))
        translated.mock(return_value=httpx.Response(200, json=_translation({_REST_ID: _STABLE_ID})))

        row = (await search_mail(client, SearchCriteria(query="invoice"), limit=25)).messages[0]

        assert row.importance is None
        assert row.flag is None
        assert row.categories == []
        assert row.is_draft is None
        assert row.sent_by is None
        assert row.reply_to == []

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
        with pytest.raises(ToolError, match="at least one of"):
            await search_mail(client, SearchCriteria(query="   "), limit=25)

        assert searched.call_count == 0

    async def test_the_refusal_names_every_criterion_search_criteria_defines(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refusal:
            await search_mail(client, SearchCriteria(), limit=25)

        message = str(refusal.value)
        for criterion in CRITERIA:
            assert criterion in message, criterion

    async def test_a_date_window_on_its_own_is_no_criterion(
        self, client: GraphServiceClient, searched: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="at least one of"):
            await search_mail(
                client,
                SearchCriteria(),
                received_after=date(2026, 9, 1),
                received_before=date(2026, 9, 30),
                limit=25,
            )

        assert searched.call_count == 0

    async def test_a_window_that_runs_backwards_never_reaches_graph(
        self, client: GraphServiceClient, searched: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="backwards"):
            await search_mail(
                client,
                SearchCriteria(query="invoice"),
                received_after=date(2026, 9, 30),
                received_before=date(2026, 9, 1),
                limit=25,
            )

        assert searched.call_count == 0

    async def test_the_backwards_refusal_names_both_bounds_and_which_takes_the_earlier_one(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refusal:
            await search_mail(
                client,
                SearchCriteria(query="invoice"),
                received_after=datetime(2026, 9, 30, 9, 0, tzinfo=UTC),
                received_before=date(2026, 9, 1),
                limit=25,
            )

        message = str(refusal.value)
        assert "`received_after`" in message
        assert "`received_before`" in message
        assert "earlier point in `received_after`" in message

    @pytest.mark.parametrize(
        ("importance", "flagged", "has_attachments", "category"),
        [
            ("high", None, None, None),
            (None, True, None, None),
            (None, None, True, None),
            (None, None, None, "Invoices"),
        ],
    )
    async def test_a_narrowing_argument_on_its_own_is_no_criterion(
        self,
        client: GraphServiceClient,
        searched: respx.Route,
        importance: MailImportance | None,
        flagged: bool | None,
        has_attachments: bool | None,
        category: str | None,
    ) -> None:
        with pytest.raises(ToolError, match="at least one of"):
            await search_mail(
                client,
                SearchCriteria(),
                importance=importance,
                flagged=flagged,
                has_attachments=has_attachments,
                category=category,
                limit=25,
            )

        assert searched.call_count == 0

    def test_the_narrowing_arguments_are_not_among_the_criteria(self) -> None:
        assert not {"importance", "has_attachments", "flagged", "category"} & set(CRITERIA)

    async def test_the_refusal_names_every_narrowing_argument_and_the_tool_for_a_folder_listing(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refusal:
            await search_mail(client, SearchCriteria(), importance="high", limit=25)

        message = str(refusal.value)
        for narrowing in (
            "received_after",
            "received_before",
            "importance",
            "has_attachments",
            "flagged",
            "category",
        ):
            assert f"`{narrowing}`" in message, narrowing
        assert "outlook_list_mail" in message

    @pytest.mark.parametrize("limit", [0, MAX_RESULTS + 1])
    async def test_a_window_outside_the_schema_is_an_assertion(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            await search_mail(client, SearchCriteria(query="invoice"), limit=limit)


class TestMailboxTargeting:
    async def test_no_mailbox_searches_the_signed_in_users_own_one(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(query="invoice"), limit=25)

        assert searched.called

    async def test_a_mailbox_searches_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        searched = graph.get("/users/alex@example.invalid/messages").mock(
            return_value=httpx.Response(200, json={"value": [_message(_REST_ID)]})
        )
        translated = graph.post("/users/alex@example.invalid/translateExchangeIds").mock(
            return_value=httpx.Response(200, json=_translation({_REST_ID: _STABLE_ID}))
        )

        found = await search_mail(
            client, SearchCriteria(query="invoice"), limit=25, mailbox="alex@example.invalid"
        )

        assert searched.called
        assert translated.called
        assert found.messages[0].uri == MailMessageHandle(_STABLE_ID).uri

    def test_the_permission_is_the_one_microsoft_documents_for_a_shared_mailbox(self) -> None:
        assert searcher.GRAPH_PERMISSIONS == ("Mail.Read", "User.Read", "Mail.Read.Shared")


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


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    searcher.register(mcp, transport)
    tool = await mcp.get_tool(searcher.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestAttachmentContentIsNotSearchable:
    async def test_the_query_field_does_not_claim_to_reach_attachment_text(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        description = cast("str", properties["query"]["description"]).casefold()
        assert "attachment" in description
        assert "not" in description

    async def test_an_attachment_name_search_still_matches_on_the_name_property_only(
        self, client: GraphServiceClient, searched: respx.Route, translated: respx.Route
    ) -> None:
        searched.mock(return_value=httpx.Response(200, json={"value": []}))
        translated.mock(return_value=httpx.Response(200, json={"value": []}))

        await search_mail(client, SearchCriteria(attachment_name="budget.pdf"), limit=25)

        assert searched.calls.last.request.url.params["$search"] == '"attachment:budget.pdf"'


class TestWhatItTellsAModel:
    async def test_the_description_keeps_its_lead_facts_and_names_the_listing_sibling(
        self, transport: httpx.AsyncClient
    ) -> None:
        _, tool = await _registered(transport)

        description = tool.description or ""
        assert "`mailbox`" in description
        assert "keyword, sender, recipient, subject, or attachment file name" in description
        assert "outlook_list_mail" in description

    async def test_the_description_is_a_lead_and_a_few_notes_of_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        _, tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "the description has no Notes section"
        assert lead.strip() != ""
        assert 1 <= len([line for line in notes.splitlines() if line.startswith("- ")]) <= 4
        assert 45 <= len(description.split()) <= 210

    async def test_the_description_says_the_narrowing_arguments_are_not_criteria(
        self, transport: httpx.AsyncClient
    ) -> None:
        _, tool = await _registered(transport)

        description = tool.description or ""
        for narrowing in ("importance", "has_attachments", "flagged", "category"):
            assert f"`{narrowing}`" in description, narrowing
        assert "not criteria" in description

    async def test_the_arguments_graph_applies_say_so_and_the_ones_the_tool_applies_say_fewer(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _ = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, str]]", parameters["properties"])
        assert (
            "Graph applies this filter inside the search" in properties["importance"]["description"]
        )
        for name in ("flagged", "has_attachments", "category"):
            described = properties[name]["description"]
            assert "applies this filter to the page that Graph returns" in described
            assert "fewer than `limit` messages" in described

    async def test_flagged_says_that_a_message_with_no_flag_matches_neither_value(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _ = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, str]]", parameters["properties"])
        described = properties["flagged"]["description"]
        assert (
            "A message for which Microsoft 365 reports no flag matches neither value." in described
        )
        assert 15 <= len(described.split()) <= 60

    async def test_more_may_exist_says_when_it_is_computed(
        self, transport: httpx.AsyncClient
    ) -> None:
        _, tool = await _registered(transport)

        assert tool.output_schema is not None
        described = cast("str", tool.output_schema["properties"]["more_may_exist"]["description"])
        assert "before it applies `flagged`, `has_attachments`, and `category`" in described

    async def test_importance_admits_the_three_values_graph_reports_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        _, tool = await _registered(transport)

        assert tool.parameters["$defs"]["MailImportance"]["enum"] == ["low", "normal", "high"]

    async def test_a_category_cannot_be_empty(self, transport: httpx.AsyncClient) -> None:
        _, tool = await _registered(transport)

        assert {"minLength": 1, "type": "string"} in tool.parameters["properties"]["category"][
            "anyOf"
        ]
