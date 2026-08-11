"""`fetch_activity_page`/`fetch_email_page`: the per-stream single-page fetch primitive.

Each test targets one behaviour called out in the design doc: the fixed `fields=`/`sort=`/
`filter[activityType][eq]` per activity stream kind, the two incompatible date dialects
(activities' one-sided-only `ge`/`le` vs email's combinable `startDate`/`endDate`), the
since-cutoff client-side truncation that only applies when both activity bounds are given, and
that a short raw page (or, for activities, a since-cutoff) is what "exhausted" means — never
`links.next`/`total_count`, which this layer's return types don't even carry.
"""

from collections.abc import KeysView
from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import fetch_activity_page, fetch_email_page
from tests.helpers import BASE_URL, client_factory, collection, credential, resource


class TestActivityRequestShape:
    @pytest.mark.asyncio
    @respx.mock
    async def test_meeting_stream_sends_fields_sort_and_activity_type(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_activity_page(
            client, segment="organizations", entity_id="42", stream="meeting", limit=10, offset=0
        )

        params = route.calls.last.request.url.params
        assert params["fields"] == (
            "title,description,effectiveDate,specificResource,createdTimestamp,modifiedTimestamp"
        )
        assert params["sort"] == "-effectiveDate"
        assert params["filter[activityType][eq]"] == "meetings"
        assert params["page[limit]"] == "10"
        assert params["page[offset]"] == "0"

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_stream_uses_calls_activity_type(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/people/7/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_activity_page(
            client, segment="people", entity_id="7", stream="call", limit=10, offset=0
        )

        assert route.calls.last.request.url.params["filter[activityType][eq]"] == "calls"

    @pytest.mark.asyncio
    @respx.mock
    async def test_note_stream_uses_notes_activity_type(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/people/7/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_activity_page(
            client, segment="people", entity_id="7", stream="note", limit=10, offset=0
        )

        assert route.calls.last.request.url.params["filter[activityType][eq]"] == "notes"

    @pytest.mark.asyncio
    @respx.mock
    async def test_document_stream_uses_documents_activity_type(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(f"{BASE_URL}/people/7/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_activity_page(
            client, segment="people", entity_id="7", stream="document", limit=10, offset=0
        )

        assert route.calls.last.request.url.params["filter[activityType][eq]"] == "documents"

    @pytest.mark.asyncio
    @respx.mock
    async def test_people_segment_builds_people_path(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/people/99/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_activity_page(
            client, segment="people", entity_id="99", stream="meeting", limit=10, offset=0
        )

        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_limit_and_offset_pass_through_to_fetch_page_under_configured_param_names(
        self,
    ) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )
        built = client_factory(page_limit_param="limit", page_offset_param="offset")
        try:
            client = built.for_credential(credential())
            await fetch_activity_page(
                client,
                segment="organizations",
                entity_id="42",
                stream="meeting",
                limit=25,
                offset=50,
            )
        finally:
            await built.aclose()

        params = route.calls.last.request.url.params
        assert params["limit"] == "25"
        assert params["offset"] == "50"
        assert "page[limit]" not in params
        assert "page[offset]" not in params


class TestActivityDateDialect:
    @pytest.mark.asyncio
    @respx.mock
    async def test_since_only_sends_ge(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_activity_page(
            client,
            segment="organizations",
            entity_id="42",
            stream="meeting",
            limit=10,
            offset=0,
            since=date(2026, 1, 1),
        )

        params = route.calls.last.request.url.params
        assert params["filter[effectiveDate][ge]"] == "2026-01-01"
        assert "filter[effectiveDate][le]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_until_only_sends_le(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_activity_page(
            client,
            segment="organizations",
            entity_id="42",
            stream="meeting",
            limit=10,
            offset=0,
            until=date(2026, 2, 1),
        )

        params = route.calls.last.request.url.params
        assert params["filter[effectiveDate][le]"] == "2026-02-01"
        assert "filter[effectiveDate][ge]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_both_bounds_sends_le_only_never_ge_and_le_together(
        self, client: BackstopClient
    ) -> None:
        """`ge`+`le` together silently 0-rows this endpoint — must never be sent together."""
        route = respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_activity_page(
            client,
            segment="organizations",
            entity_id="42",
            stream="meeting",
            limit=10,
            offset=0,
            since=date(2026, 1, 10),
            until=date(2026, 2, 1),
        )

        params = route.calls.last.request.url.params
        assert params["filter[effectiveDate][le]"] == "2026-02-01"
        assert "filter[effectiveDate][ge]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_neither_bound_sends_no_date_filter(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_activity_page(
            client, segment="organizations", entity_id="42", stream="meeting", limit=10, offset=0
        )

        params = route.calls.last.request.url.params
        assert "filter[effectiveDate][ge]" not in params
        assert "filter[effectiveDate][le]" not in params


def _activity(id_: str, effective_date: str) -> dict[str, object]:
    return resource(id_, "activities", title=f"Item {id_}", effectiveDate=effective_date)


class TestActivityExhaustion:
    @pytest.mark.asyncio
    @respx.mock
    async def test_short_raw_page_is_exhausted(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(
                200, json=collection(_activity("meeting-or-calls_1", "2026-01-15"))
            )
        )

        page = await fetch_activity_page(
            client, segment="organizations", entity_id="42", stream="meeting", limit=5, offset=0
        )

        assert len(page.items) == 1
        assert page.end_of_stream is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_full_raw_page_with_no_cutoff_is_not_exhausted(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    _activity("meeting-or-calls_1", "2026-01-15"),
                    _activity("meeting-or-calls_2", "2026-01-14"),
                ),
            )
        )

        page = await fetch_activity_page(
            client, segment="organizations", entity_id="42", stream="meeting", limit=2, offset=0
        )

        assert len(page.items) == 2
        assert page.end_of_stream is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_since_cutoff_mid_page_is_exhausted_even_when_raw_page_is_full(
        self, client: BackstopClient
    ) -> None:
        """Both-bounds case: hitting the `since` cutoff exhausts the stream even though the raw
        page came back exactly at `limit` (Backstop still had more to give, but this window is
        done).
        """
        respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    _activity("meeting-or-calls_1", "2026-01-31"),
                    _activity("meeting-or-calls_2", "2026-01-20"),
                    _activity("meeting-or-calls_3", "2026-01-05"),
                    _activity("meeting-or-calls_4", "2026-01-01"),
                ),
            )
        )

        page = await fetch_activity_page(
            client,
            segment="organizations",
            entity_id="42",
            stream="meeting",
            limit=4,
            offset=0,
            since=date(2026, 1, 10),
            until=date(2026, 2, 1),
        )

        assert [item.id for item in page.items] == ["meeting-or-calls_1", "meeting-or-calls_2"]
        assert page.end_of_stream is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_both_bounds_with_no_cutoff_hit_and_short_page_reports_short_page_reason(
        self, client: BackstopClient
    ) -> None:
        """The RAW count (before since-truncation) drives the short-page branch — a raw short
        page with nothing to truncate is still exhausted, for the ordinary reason.
        """
        respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(
                200, json=collection(_activity("meeting-or-calls_1", "2026-01-31"))
            )
        )

        page = await fetch_activity_page(
            client,
            segment="organizations",
            entity_id="42",
            stream="meeting",
            limit=5,
            offset=0,
            since=date(2026, 1, 10),
            until=date(2026, 2, 1),
        )

        assert len(page.items) == 1
        assert page.end_of_stream is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_future_dated_items_are_not_dropped(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    _activity("meeting-or-calls_1", "2099-01-01"),
                    _activity("meeting-or-calls_2", "2026-01-01"),
                ),
            )
        )

        page = await fetch_activity_page(
            client, segment="organizations", entity_id="42", stream="meeting", limit=5, offset=0
        )

        assert [item.id for item in page.items] == ["meeting-or-calls_1", "meeting-or-calls_2"]
        assert page.items[0].effective_date == date(2099, 1, 1)


class TestActivityParsing:
    @pytest.mark.asyncio
    @respx.mock
    async def test_carries_requested_stream_and_specific_resource(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource(
                        "meeting-or-calls_76280387",
                        "activities",
                        title="Quarterly Review",
                        description="<p>notes</p>",
                        effectiveDate="2026-01-15",
                        specificResource={
                            "resourceType": "meeting-or-calls",
                            "resourceId": "76280387",
                        },
                        createdTimestamp="2026-01-10T00:00:00.000-0500",
                        modifiedTimestamp="2026-01-12T00:00:00.000-0500",
                    )
                ),
            )
        )

        page = await fetch_activity_page(
            client, segment="organizations", entity_id="42", stream="call", limit=5, offset=0
        )

        assert len(page.items) == 1
        item = page.items[0]
        assert item.id == "meeting-or-calls_76280387"
        assert item.stream == "call"
        assert item.title == "Quarterly Review"
        assert item.description == "<p>notes</p>"
        assert item.effective_date == date(2026, 1, 15)
        assert item.resource_type == "meeting-or-calls"
        assert item.resource_id == "76280387"
        assert item.created_timestamp is not None
        assert item.modified_timestamp is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_links_next_and_total_count_are_never_read(self, client: BackstopClient) -> None:
        """Present in the mocked response (as they legitimately are on an unfiltered request),
        but `ActivityPage` has no field to carry them into, so there's no way for this layer to
        act on them even if it tried.
        """
        respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [_activity("meeting-or-calls_1", "2026-01-15")],
                    "links": {"next": f"{BASE_URL}/organizations/42/activities?page[offset]=5"},
                    "meta": {"totalResourceCount": 999},
                },
            )
        )

        page = await fetch_activity_page(
            client, segment="organizations", entity_id="42", stream="meeting", limit=5, offset=0
        )

        assert len(page.items) == 1
        assert not hasattr(page, "total_count")
        assert not hasattr(page, "next_path")


def _email(id_: str, sent_timestamp: str) -> dict[str, object]:
    return resource(id_, "emails", subject=f"Subject {id_}", sentTimestamp=sent_timestamp)


class TestEmailRequestShape:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_fixed_fields_and_sort(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_email_page(client, segment="organizations", entity_id="42", limit=10, offset=0)

        params = route.calls.last.request.url.params
        assert params["fields"] == (
            "subject,sentTimestamp,fromEmail,toEmails,ccEmails,hasAttachments,contentUrl"
        )
        assert params["sort"] == "-sentTimestamp"
        assert params["page[limit]"] == "10"
        assert params["page[offset]"] == "0"

    @pytest.mark.asyncio
    @respx.mock
    async def test_people_segment_builds_people_emails_path(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/people/7/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_email_page(client, segment="people", entity_id="7", limit=10, offset=0)

        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_limit_and_offset_pass_through_to_fetch_page_under_configured_param_names(
        self,
    ) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )
        built = client_factory(page_limit_param="limit", page_offset_param="offset")
        try:
            client = built.for_credential(credential())
            await fetch_email_page(
                client, segment="organizations", entity_id="42", limit=25, offset=50
            )
        finally:
            await built.aclose()

        params = route.calls.last.request.url.params
        assert params["limit"] == "25"
        assert params["offset"] == "50"
        assert "page[limit]" not in params


class TestEmailDateDialect:
    @pytest.mark.asyncio
    @respx.mock
    async def test_since_only_sends_start_date(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_email_page(
            client,
            segment="organizations",
            entity_id="42",
            limit=10,
            offset=0,
            since=date(2026, 1, 1),
        )

        params = route.calls.last.request.url.params
        assert params["filter[startDate]"] == "2026-01-01"
        assert "filter[endDate]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_until_only_sends_end_date(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_email_page(
            client,
            segment="organizations",
            entity_id="42",
            limit=10,
            offset=0,
            until=date(2026, 2, 1),
        )

        params = route.calls.last.request.url.params
        assert params["filter[endDate]"] == "2026-02-01"
        assert "filter[startDate]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_both_bounds_send_both_independently(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_email_page(
            client,
            segment="organizations",
            entity_id="42",
            limit=10,
            offset=0,
            since=date(2026, 1, 1),
            until=date(2026, 2, 1),
        )

        params = route.calls.last.request.url.params
        assert params["filter[startDate]"] == "2026-01-01"
        assert params["filter[endDate]"] == "2026-02-01"

    @pytest.mark.asyncio
    @respx.mock
    async def test_neither_bound_sends_no_date_filter(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_email_page(client, segment="organizations", entity_id="42", limit=10, offset=0)

        params = route.calls.last.request.url.params
        assert "filter[startDate]" not in params
        assert "filter[endDate]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_sent_timestamp_filter_is_never_sent(self, client: BackstopClient) -> None:
        """`filter[sentTimestamp][ge]` is silently ignored by Backstop — accepted, count
        unchanged, wrong answer, no error — so this must never appear on the wire.
        """
        route = respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await fetch_email_page(
            client,
            segment="organizations",
            entity_id="42",
            limit=10,
            offset=0,
            since=date(2026, 1, 1),
            until=date(2026, 2, 1),
        )

        params = route.calls.last.request.url.params
        sent_param_names: KeysView[str] = params.keys()
        assert not any(name.startswith("filter[sentTimestamp]") for name in sent_param_names)


class TestEmailExhaustion:
    @pytest.mark.asyncio
    @respx.mock
    async def test_short_raw_page_is_exhausted(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(
                200, json=collection(_email("e1", "2026-01-15T00:00:00.000-0500"))
            )
        )

        page = await fetch_email_page(
            client, segment="organizations", entity_id="42", limit=5, offset=0
        )

        assert len(page.items) == 1
        assert page.end_of_stream is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_full_raw_page_is_not_exhausted(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    _email("e1", "2026-01-15T00:00:00.000-0500"),
                    _email("e2", "2026-01-14T00:00:00.000-0500"),
                ),
            )
        )

        page = await fetch_email_page(
            client, segment="organizations", entity_id="42", limit=2, offset=0
        )

        assert len(page.items) == 2
        assert page.end_of_stream is False


class TestEmailParsing:
    @pytest.mark.asyncio
    @respx.mock
    async def test_parses_email_attributes(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource(
                        "email_1",
                        "emails",
                        subject="Re: Follow-up",
                        sentTimestamp="2026-06-25T00:00:00.000-0400",
                        fromEmail="ada@example.com",
                        toEmails=["bob@example.com"],
                        ccEmails=["carol@example.com", "dave@example.com"],
                        hasAttachments=True,
                        contentUrl="https://example.backstopsolutions.com/emails/1/content",
                    )
                ),
            )
        )

        page = await fetch_email_page(
            client, segment="organizations", entity_id="42", limit=5, offset=0
        )

        assert len(page.items) == 1
        item = page.items[0]
        assert item.id == "email_1"
        assert item.subject == "Re: Follow-up"
        assert item.sent_timestamp is not None
        assert item.sent_timestamp.year == 2026
        assert item.from_email == "ada@example.com"
        assert item.to_emails == ("bob@example.com",)
        assert item.cc_emails == ("carol@example.com", "dave@example.com")
        assert item.has_attachments is True
        assert item.content_url == "https://example.backstopsolutions.com/emails/1/content"

    @pytest.mark.asyncio
    @respx.mock
    async def test_links_next_and_total_count_are_never_read(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [_email("e1", "2026-01-15T00:00:00.000-0500")],
                    "links": {"next": f"{BASE_URL}/organizations/42/emails?page[offset]=5"},
                    "meta": {"totalResourceCount": 999},
                },
            )
        )

        page = await fetch_email_page(
            client, segment="organizations", entity_id="42", limit=5, offset=0
        )

        assert len(page.items) == 1
        assert not hasattr(page, "total_count")
        assert not hasattr(page, "next_path")
