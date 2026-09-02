"""Per-stream single-page fetch via `GetActivityHistoryQuery.run`.

Each test targets one behaviour called out in the design doc: the fixed `fields=`/`sort=`/
`filter[activityType][eq]` per activity stream kind, the two incompatible date dialects
(activities' one-sided-only `ge`/`le` vs email's combinable `startDate`/`endDate`), the
since-cutoff client-side truncation that only applies when both activity bounds are given, and
that a short raw page (or, for activities, a since-cutoff) is what "exhausted" means — never
`links.next`/`total_count`, which this layer's return types don't even carry.
"""

from collections.abc import KeysView
from datetime import date
from urllib.parse import quote

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import (
    ActivityContinuationResponse,
    ActivityGroupResponse,
    ActivityType,
    Segment,
    TimelineRecord,
)
from backstop_mcp.features.party_resolver import ResolvedPartyDto
from tests.features.activity_history.conftest import make_get_activity_history_query
from tests.helpers import BASE_URL, client_factory, collection, credential, resource


def _mock_party(segment: str, entity_id: str) -> None:
    respx.get(f"{BASE_URL}/{segment}/{quote(entity_id, safe='')}").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"type": segment, "id": entity_id, "attributes": {"name": "Party"}}},
        )
    )


async def _run_stream(
    client: BackstopClient,
    *,
    segment: Segment,
    entity_id: str,
    stream: ActivityType,
    limit: int = 10,
    offset: int = 0,
    since: date | None = None,
    until: date | None = None,
    activity_tag_ids: tuple[str, ...] = (),
) -> ActivityGroupResponse[TimelineRecord]:
    _mock_party(segment, entity_id)
    result = await make_get_activity_history_query(client).run(
        segment=segment,
        entity_id=entity_id,
        party=ResolvedPartyDto(id=entity_id, search_type=segment, name="Party"),
        continuations={
            stream: ActivityContinuationResponse(
                limit=limit,
                offset=offset,
                since=since,
                until=until,
                activity_tag_ids=activity_tag_ids or None,
            )
        },
        gist_max_chars=300,
    )
    return result.groups[stream]


class TestActivityRequestShape:
    @pytest.mark.asyncio
    @respx.mock
    async def test_meeting_stream_sends_fields_sort_and_activity_type(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await _run_stream(
            client, segment="organizations", entity_id="42", stream="meeting", limit=10, offset=0
        )

        params = route.calls.last.request.url.params
        assert params["fields"] == (
            "title,description,effectiveDate,specificResource,createdTimestamp,modifiedTimestamp"
        )
        assert params["include"] == "activityTags"
        assert params["fields[activity-tags]"] == "name"
        assert "fields[people]" not in params
        assert "regarding" not in params["fields"]
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

        await _run_stream(
            client, segment="people", entity_id="7", stream="call", limit=10, offset=0
        )

        assert route.calls.last.request.url.params["filter[activityType][eq]"] == "calls"

    @pytest.mark.asyncio
    @respx.mock
    async def test_note_stream_uses_notes_activity_type(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/people/7/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await _run_stream(
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

        await _run_stream(
            client, segment="people", entity_id="7", stream="document", limit=10, offset=0
        )

        assert route.calls.last.request.url.params["filter[activityType][eq]"] == "documents"

    @pytest.mark.asyncio
    @respx.mock
    async def test_people_segment_builds_people_path(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/people/99/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await _run_stream(
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
            await _run_stream(
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

        await _run_stream(
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

        await _run_stream(
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

        await _run_stream(
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

        await _run_stream(
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

        page = await _run_stream(
            client, segment="organizations", entity_id="42", stream="meeting", limit=5, offset=0
        )

        assert len(page.items) == 1
        assert page.next is None

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

        page = await _run_stream(
            client, segment="organizations", entity_id="42", stream="meeting", limit=2, offset=0
        )

        assert len(page.items) == 2
        assert page.next is not None

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

        page = await _run_stream(
            client,
            segment="organizations",
            entity_id="42",
            stream="meeting",
            limit=4,
            offset=0,
            since=date(2026, 1, 10),
            until=date(2026, 2, 1),
        )

        assert [item.activity_id for item in page.items] == [
            "meeting-or-calls_1",
            "meeting-or-calls_2",
        ]
        assert page.next is None

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

        page = await _run_stream(
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
        assert page.next is None

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

        page = await _run_stream(
            client, segment="organizations", entity_id="42", stream="meeting", limit=5, offset=0
        )

        assert [item.activity_id for item in page.items] == [
            "meeting-or-calls_1",
            "meeting-or-calls_2",
        ]
        assert page.items[0].occurred_at == date(2099, 1, 1)


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

        page = await _run_stream(
            client, segment="organizations", entity_id="42", stream="call", limit=5, offset=0
        )

        assert len(page.items) == 1
        item = page.items[0]
        assert item.activity_id == "meeting-or-calls_76280387"
        assert item.type == "call"
        assert item.title == "Quarterly Review"
        assert item.gist == "notes"
        assert item.occurred_at == date(2026, 1, 15)
        assert item.resource_id == "76280387"

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

        page = await _run_stream(
            client, segment="organizations", entity_id="42", stream="meeting", limit=5, offset=0
        )

        assert len(page.items) == 1
        assert not hasattr(page, "total_count")
        assert not hasattr(page, "next_path")

    @pytest.mark.asyncio
    @respx.mock
    async def test_entity_id_path_segment_is_percent_encoded(self, client: BackstopClient) -> None:
        """Slash-bearing entity ids must not reshape the authenticated CRM path."""
        route = respx.get(f"{BASE_URL}/organizations/foo%2F..%2Fbar/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await _run_stream(
            client,
            segment="organizations",
            entity_id="foo/../bar",
            stream="meeting",
            limit=5,
            offset=0,
        )

        assert route.call_count == 1
        assert "/organizations/foo%2F..%2Fbar/activities" in str(route.calls.last.request.url)


def _email(id_: str, sent_timestamp: str) -> dict[str, object]:
    return resource(id_, "emails", subject=f"Subject {id_}", sentTimestamp=sent_timestamp)


class TestEmailRequestShape:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_fixed_fields_and_sort(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await _run_stream(
            client, stream="email", segment="organizations", entity_id="42", limit=10, offset=0
        )

        params = route.calls.last.request.url.params
        assert params["fields"] == (
            "subject,sentTimestamp,fromEmail,toEmails,ccEmails,hasAttachments,contentUrl"
        )
        assert params["sort"] == "-sentTimestamp"
        assert params["page[limit]"] == "10"
        assert params["page[offset]"] == "0"
        assert "include" not in params
        assert "filter[activityTagIds]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_people_segment_builds_people_emails_path(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/people/7/emails").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await _run_stream(
            client, stream="email", segment="people", entity_id="7", limit=10, offset=0
        )

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
            await _run_stream(
                client, stream="email", segment="organizations", entity_id="42", limit=25, offset=50
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

        await _run_stream(
            client,
            stream="email",
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

        await _run_stream(
            client,
            stream="email",
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

        await _run_stream(
            client,
            stream="email",
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

        await _run_stream(
            client, stream="email", segment="organizations", entity_id="42", limit=10, offset=0
        )

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

        await _run_stream(
            client,
            stream="email",
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

        page = await _run_stream(
            client, stream="email", segment="organizations", entity_id="42", limit=5, offset=0
        )

        assert len(page.items) == 1
        assert page.next is None

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

        page = await _run_stream(
            client, stream="email", segment="organizations", entity_id="42", limit=2, offset=0
        )

        assert len(page.items) == 2
        assert page.next is not None


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

        page = await _run_stream(
            client, stream="email", segment="organizations", entity_id="42", limit=5, offset=0
        )

        assert len(page.items) == 1
        item = page.items[0]
        assert item.activity_id == "email_1"
        assert item.subject == "Re: Follow-up"
        assert item.occurred_at is not None
        assert item.occurred_at.year == 2026
        assert item.from_email == "ada@example.com"
        assert item.to_emails == ("bob@example.com",)
        assert item.cc_emails == ("carol@example.com", "dave@example.com")
        assert item.has_attachments is True

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

        page = await _run_stream(
            client, stream="email", segment="organizations", entity_id="42", limit=5, offset=0
        )

        assert len(page.items) == 1
        assert not hasattr(page, "total_count")
        assert not hasattr(page, "next_path")


class TestActivityTagFilterAndIncludes:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_comma_separated_tag_ids_without_an_operator(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await _run_stream(
            client,
            segment="organizations",
            entity_id="42",
            stream="meeting",
            limit=10,
            offset=0,
            activity_tag_ids=("474963", "88"),
        )

        params = route.calls.last.request.url.params
        assert params["filter[activityTagIds]"] == "474963,88"

    @pytest.mark.asyncio
    @respx.mock
    async def test_omits_the_tag_filter_when_no_ids_are_given(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await _run_stream(
            client, segment="organizations", entity_id="42", stream="note", limit=10, offset=0
        )

        assert "filter[activityTagIds]" not in route.calls.last.request.url.params

    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_tags_from_one_page_and_does_not_follow_attendee_links(
        self, client: BackstopClient
    ) -> None:
        tag_by_id = respx.get(f"{BASE_URL}/activity-tags/474963").mock(
            return_value=httpx.Response(500)
        )
        attendees = respx.get(f"{BASE_URL}/meeting-or-calls/1/attendees").mock(
            return_value=httpx.Response(500)
        )
        respx.get(f"{BASE_URL}/organizations/42/activities").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "type": "activities",
                            "id": "meeting-or-calls_1",
                            "attributes": {
                                "title": "Quarterly Review",
                                "effectiveDate": "2026-01-15",
                                "regarding": {
                                    "resourceId": "o42",
                                    "resourceType": "organizations",
                                },
                            },
                            "relationships": {
                                "activityTags": {
                                    "data": [{"type": "activity-tags", "id": "474963"}]
                                },
                                "attendees": {"data": [{"type": "people", "id": "p1"}]},
                            },
                        }
                    ],
                    "included": [
                        resource("474963", "activity-tags", name="Quarterly Review"),
                        resource("p1", "people", name="Pat Lee"),
                    ],
                    "links": {"next": None},
                },
            )
        )

        page = await _run_stream(
            client, segment="organizations", entity_id="42", stream="meeting", limit=10, offset=0
        )

        assert tag_by_id.call_count == 0
        assert attendees.call_count == 0
        item = page.items[0]
        assert item.regarding is not None
        assert item.regarding.id == "o42"
        assert item.regarding.resource_type == "organizations"
        assert item.regarding.search_type == "organizations"
        assert [(tag.id, tag.name) for tag in item.tags] == [("474963", "Quarterly Review")]
        assert item.attendees == ()
