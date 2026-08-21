"""`get_activity_history`: party resolution, stream fan-out, and grouped-page round-trip.

Each test targets one behaviour from the task: the default-stream fan-out (all five streams,
including `document`), that a resumed call (`type="next"`) skips resolution and only re-fetches
streams present in `next`, that invalid `next` inputs raise pydantic `ValidationError`, that a
5xx on one stream fails the whole call, and that a 403 on one stream is reported on that group
without discarding the others.
"""

from collections.abc import Sequence
from datetime import date

import httpx
import pytest
import respx
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.activity_history import (
    ActivityContinuationResponse,
    ActivityHistoryResolvedResponse,
    ActivityHistorySettings,
    ActivityRecordResponse,
    ActivityType,
    EmailRecordResponse,
    ResolvedPartyAsOfResponse,
    TimelineRecord,
)
from backstop_mcp.features.activity_history.tools.get_activity_history import (
    ActivityHistoryFirstPageInput,
    ActivityHistoryNextPageInput,
    get_activity_history,
)
from backstop_mcp.features.data_hygiene import AsOfResponse
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import PartyAmbiguousResponse, PartyCandidateResponse
from backstop_mcp.features.resolution import NotFoundResponse
from tests.features.party_resolver.helpers import (
    BASE_URL,
    collection,
    ctx_decline,
    ctx_never_elicit,
    resource,
)
from tests.server.tools.helpers import object_dict, tool_model, tool_model_union, tool_payload

_SETTINGS = ActivityHistorySettings(page_size=10, gist_max_chars=300)


def _org_document(
    org_id: str = "o42", name: str = "Capstone", *, modified_by: str = "ops"
) -> dict[str, object]:
    return {
        "data": {
            "type": "organizations",
            "id": org_id,
            "attributes": {
                "name": name,
                "modifiedTimestamp": "2025-03-01T10:00:00Z",
                "modifiedBy": modified_by,
            },
        }
    }


def _activity(id_: str, effective_date: str) -> dict[str, object]:
    return resource(id_, "activities", title=f"Item {id_}", effectiveDate=effective_date)


def _email(id_: str, sent_timestamp: str) -> dict[str, object]:
    return resource(id_, "emails", subject=f"Subject {id_}", sentTimestamp=sent_timestamp)


def _activities_route(segment: str, entity_id: str, activity_type: str) -> respx.Route:
    return respx.get(
        f"{BASE_URL}/{segment}/{entity_id}/activities",
        params={"filter[activityType][eq]": activity_type},
    )


def _emails_route(segment: str, entity_id: str) -> respx.Route:
    return respx.get(f"{BASE_URL}/{segment}/{entity_id}/emails")


def _first(**kwargs: object) -> ActivityHistoryFirstPageInput:
    return ActivityHistoryFirstPageInput.model_validate({"type": "first", **kwargs})


def _next(
    *,
    search_type: SearchType,
    entity_id: str,
    next: dict[ActivityType, ActivityContinuationResponse],
) -> ActivityHistoryNextPageInput:
    return ActivityHistoryNextPageInput(
        type="next", search_type=search_type, entity_id=entity_id, next=next
    )


def _record_keys(items: Sequence[TimelineRecord]) -> list[tuple[str, str]]:
    return [(record.type, record.activity_id) for record in items]


class TestGetActivityHistoryDocstring:
    def test_names_itself_the_documented_fallback(self) -> None:
        doc = get_activity_history.__doc__ or ""
        assert "search_activities" in doc
        assert "fallback" in doc
        assert "include_description" in doc


class TestFirstCallByTrustedPartyId:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_default_streams_including_document(self, client: BackstopClient) -> None:

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_document())
        )
        _activities_route("organizations", "o42", "meetings").mock(
            return_value=httpx.Response(200, json=collection(_activity("m1", "2026-01-05")))
        )
        _activities_route("organizations", "o42", "calls").mock(
            return_value=httpx.Response(200, json=collection(_activity("c1", "2026-01-04")))
        )
        _activities_route("organizations", "o42", "notes").mock(
            return_value=httpx.Response(200, json=collection(_activity("n1", "2026-01-03")))
        )
        documents = _activities_route("organizations", "o42", "documents").mock(
            return_value=httpx.Response(200, json=collection(_activity("d1", "2026-02-15")))
        )
        emails_json = collection(
            *(_email(f"e{i}", f"2026-02-{10 - i:02d}T00:00:00.000-0500") for i in range(10))
        )
        _emails_route("organizations", "o42").mock(
            return_value=httpx.Response(200, json=emails_json)
        )

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _first(search_type="organizations", party_id="o42"),
                client=client,
                activity_history=_SETTINGS,
            ),
            ActivityHistoryResolvedResponse,
        )

        assert result.resolved == ResolvedPartyAsOfResponse(
            id="o42",
            search_type="organizations",
            name="Capstone",
            as_of=AsOfResponse(modified_timestamp="2025-03-01T10:00:00Z", modified_by="ops"),
        )
        assert documents.call_count == 1
        assert set(result.groups) == {"meeting", "call", "note", "email", "document"}
        assert _record_keys(result.groups["meeting"].items) == [("meeting", "m1")]
        assert _record_keys(result.groups["call"].items) == [("call", "c1")]
        assert _record_keys(result.groups["note"].items) == [("note", "n1")]
        assert _record_keys(result.groups["document"].items) == [("document", "d1")]
        assert _record_keys(result.groups["email"].items) == [("email", f"e{i}") for i in range(10)]
        assert all(
            isinstance(record, EmailRecordResponse) for record in result.groups["email"].items
        )
        meeting = result.groups["meeting"].items[0]
        assert isinstance(meeting, ActivityRecordResponse)
        assert meeting.occurred_at == date(2026, 1, 5)
        assert result.groups["email"].next is not None
        assert result.groups["meeting"].next is None


class TestFirstCallBySearch:
    @pytest.mark.asyncio
    @respx.mock
    async def test_resolves_uniquely_and_returns_the_requested_stream(
        self, client: BackstopClient
    ) -> None:

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200, json=collection(resource("o7", "organizations", name="Capstone"))
            )
        )
        respx.get(f"{BASE_URL}/organizations/o7").mock(
            return_value=httpx.Response(200, json=_org_document(org_id="o7"))
        )
        _activities_route("organizations", "o7", "meetings").mock(
            return_value=httpx.Response(200, json=collection(_activity("m1", "2026-01-05")))
        )

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _first(
                    search_type="organizations",
                    search="Capstone",
                    activity_types=["meeting"],
                ),
                client=client,
                activity_history=_SETTINGS,
            ),
            ActivityHistoryResolvedResponse,
        )

        assert result.resolved.id == "o7"
        assert set(result.groups) == {"meeting"}
        assert _record_keys(result.groups["meeting"].items) == [("meeting", "m1")]
        first = result.groups["meeting"].items[0]
        assert isinstance(first, ActivityRecordResponse)
        assert first.title == "Item m1"
        assert result.groups["meeting"].next is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_search_returns_candidates_without_fetching_timeline(
        self, client: BackstopClient
    ) -> None:

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o1", "organizations", name="Capstone A"),
                    resource("o2", "organizations", name="Capstone B"),
                ),
            )
        )
        org_get = respx.get(url__regex=rf"{BASE_URL}/organizations/\w+").mock(
            return_value=httpx.Response(200, json={})
        )

        result = tool_model(
            await get_activity_history(
                ctx_decline(),
                _first(search_type="organizations", search="Capstone"),
                client=client,
                activity_history=_SETTINGS,
            ),
            PartyAmbiguousResponse,
        )

        assert result == PartyAmbiguousResponse(
            query="Capstone",
            scope="organizations",
            candidates=[
                PartyCandidateResponse(
                    key="organizations:o1",
                    label="Capstone A (organization)",
                    id="o1",
                    search_type="organizations",
                    name="Capstone A",
                ),
                PartyCandidateResponse(
                    key="organizations:o2",
                    label="Capstone B (organization)",
                    id="o2",
                    search_type="organizations",
                    name="Capstone B",
                ),
            ],
        )
        assert org_get.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_not_found_search_returns_the_query_it_used(self, client: BackstopClient) -> None:

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/people").mock(return_value=httpx.Response(200, json=collection()))

        result = tool_model_union(
            await get_activity_history(
                ctx_never_elicit(),
                _first(search_type="people", search="Nope"),
                client=client,
                activity_history=_SETTINGS,
            ),
            ActivityHistoryResolvedResponse | PartyAmbiguousResponse | NotFoundResponse,
        )

        assert isinstance(result, NotFoundResponse)
        assert result.query == "Nope"
        assert result.scope == "people"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_resolved_collection_when_person_hit_is_a_contact(
        self, client: BackstopClient
    ) -> None:
        """Person quick-search can return contacts; timeline paths must follow search_type."""

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("c9", "contacts", name="Jane Contact")),
            )
        )
        contact_get = respx.get(f"{BASE_URL}/contacts/c9").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "contacts",
                        "id": "c9",
                        "attributes": {"name": "Jane Contact"},
                        "relationships": {"entityRelationships": {"data": []}},
                    },
                    "included": [],
                },
            )
        )
        people_get = respx.get(url__regex=rf"{BASE_URL}/people/\w+").mock(
            return_value=httpx.Response(200, json={})
        )
        _activities_route("contacts", "c9", "meetings").mock(
            return_value=httpx.Response(200, json=collection(_activity("m1", "2026-01-05")))
        )
        for activity_type in ("calls", "notes"):
            _activities_route("contacts", "c9", activity_type).mock(
                return_value=httpx.Response(200, json=collection())
            )
        _emails_route("contacts", "c9").mock(return_value=httpx.Response(200, json=collection()))

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _first(search_type="people", search="Jane Contact", activity_types=["meeting"]),
                client=client,
                activity_history=_SETTINGS,
            ),
            ActivityHistoryResolvedResponse,
        )

        assert result.resolved == ResolvedPartyAsOfResponse(
            id="c9", search_type="contacts", name="Jane Contact"
        )
        assert contact_get.call_count == 1
        assert people_get.call_count == 0
        assert _record_keys(result.groups["meeting"].items) == [("meeting", "m1")]

    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_contact_party_id_fetches_contacts_collection(
        self, client: BackstopClient
    ) -> None:

        contact_get = respx.get(f"{BASE_URL}/contacts/c9").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "contacts",
                        "id": "c9",
                        "attributes": {"name": "Jane Contact"},
                        "relationships": {"entityRelationships": {"data": []}},
                    },
                    "included": [],
                },
            )
        )
        people_get = respx.get(url__regex=rf"{BASE_URL}/people/\w+").mock(
            return_value=httpx.Response(200, json={})
        )
        _activities_route("contacts", "c9", "meetings").mock(
            return_value=httpx.Response(200, json=collection(_activity("m1", "2026-01-05")))
        )
        for activity_type in ("calls", "notes"):
            _activities_route("contacts", "c9", activity_type).mock(
                return_value=httpx.Response(200, json=collection())
            )
        _emails_route("contacts", "c9").mock(return_value=httpx.Response(200, json=collection()))

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _first(
                    party_id="c9",
                    search_type="contacts",
                    activity_types=["meeting"],
                ),
                client=client,
                activity_history=_SETTINGS,
            ),
            ActivityHistoryResolvedResponse,
        )

        assert result.resolved == ResolvedPartyAsOfResponse(
            id="c9", search_type="contacts", name="Jane Contact"
        )
        assert contact_get.call_count == 1
        assert people_get.call_count == 0
        assert _record_keys(result.groups["meeting"].items) == [("meeting", "m1")]


class TestResumedCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_resolution_and_only_refetches_open_streams(
        self, client: BackstopClient
    ) -> None:

        quick = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_document())
        )
        meetings = _activities_route("organizations", "o42", "meetings").mock(
            return_value=httpx.Response(200, json=collection(_activity("m4", "2026-01-01")))
        )
        notes = _activities_route("organizations", "o42", "notes").mock(
            return_value=httpx.Response(200, json=collection(_activity("n9", "2026-01-01")))
        )

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _next(
                    search_type="organizations",
                    entity_id="o42",
                    next={"meeting": ActivityContinuationResponse(limit=10, offset=3)},
                ),
                client=client,
                activity_history=_SETTINGS,
            ),
            ActivityHistoryResolvedResponse,
        )

        assert quick.call_count == 0
        assert notes.call_count == 0
        assert meetings.call_count == 1
        assert result.resolved.id == "o42"
        assert result.resolved.search_type == "organizations"
        assert set(result.groups) == {"meeting"}
        assert _record_keys(result.groups["meeting"].items) == [("meeting", "m4")]
        assert result.groups["meeting"].next is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_rebuilds_person_name_from_first_and_last_on_next_page(
        self, client: BackstopClient
    ) -> None:
        """Next pages omit ResolvedPartyDto.name; the party GET often has first/last name only."""

        respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "people",
                        "id": "p9",
                        "attributes": {
                            "firstName": "Jane",
                            "lastName": "Doe",
                            "modifiedTimestamp": "2025-03-01T10:00:00Z",
                            "modifiedBy": "ops",
                        },
                    }
                },
            )
        )
        _activities_route("people", "p9", "meetings").mock(
            return_value=httpx.Response(200, json=collection(_activity("m4", "2026-01-01")))
        )

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _next(
                    search_type="people",
                    entity_id="p9",
                    next={"meeting": ActivityContinuationResponse(limit=10, offset=3)},
                ),
                client=client,
                activity_history=_SETTINGS,
            ),
            ActivityHistoryResolvedResponse,
        )

        assert result.resolved == ResolvedPartyAsOfResponse(
            id="p9",
            search_type="people",
            name="Jane Doe",
            as_of=AsOfResponse(modified_timestamp="2025-03-01T10:00:00Z", modified_by="ops"),
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_first_page_email_next_resumes_only_the_email_stream(
        self, client: BackstopClient
    ) -> None:

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_document())
        )
        meetings = _activities_route("organizations", "o42", "meetings").mock(
            return_value=httpx.Response(200, json=collection(_activity("m1", "2026-01-05")))
        )
        calls = _activities_route("organizations", "o42", "calls").mock(
            return_value=httpx.Response(200, json=collection(_activity("c1", "2026-01-04")))
        )
        notes = _activities_route("organizations", "o42", "notes").mock(
            return_value=httpx.Response(200, json=collection(_activity("n1", "2026-01-03")))
        )
        documents = _activities_route("organizations", "o42", "documents").mock(
            return_value=httpx.Response(200, json=collection(_activity("d1", "2026-02-15")))
        )
        first_emails = collection(
            *(_email(f"e{i}", f"2026-02-{10 - i:02d}T00:00:00.000-0500") for i in range(10))
        )
        second_emails = collection(_email("e10", "2026-01-31T00:00:00.000-0500"))
        emails = _emails_route("organizations", "o42").mock(
            side_effect=[
                httpx.Response(200, json=first_emails),
                httpx.Response(200, json=second_emails),
            ]
        )

        first_result = await get_activity_history(
            ctx_never_elicit(),
            _first(search_type="organizations", party_id="o42"),
            client=client,
            activity_history=_SETTINGS,
        )
        first_payload = tool_payload(first_result)

        groups = object_dict(first_payload["groups"])
        meeting_group = object_dict(groups["meeting"])
        assert "next" not in meeting_group

        email_group = object_dict(groups["email"])
        raw_email_next = object_dict(email_group["next"])
        assert "since" not in raw_email_next
        assert "until" not in raw_email_next

        resolved = object_dict(first_payload["resolved"])
        second_result = await get_activity_history(
            ctx_never_elicit(),
            ActivityHistoryNextPageInput.model_validate(
                {
                    "type": "next",
                    "search_type": resolved["search_type"],
                    "entity_id": resolved["id"],
                    "next": {"email": raw_email_next},
                }
            ),
            client=client,
            activity_history=_SETTINGS,
        )
        second_payload = tool_payload(second_result)
        second = tool_model(second_result, ActivityHistoryResolvedResponse)
        second_groups = object_dict(second_payload["groups"])
        second_email = object_dict(second_groups["email"])
        assert "next" not in second_email

        assert emails.call_count == 2
        assert meetings.call_count == 1
        assert calls.call_count == 1
        assert notes.call_count == 1
        assert documents.call_count == 1
        assert set(second.groups) == {"email"}
        assert _record_keys(second.groups["email"].items) == [("email", "e10")]
        assert second.groups["email"].next is None


class TestRequestShape:
    def test_first_page_input_requires_search_type(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate({"type": "first", "party_id": "o42"})

    def test_first_page_input_rejects_non_positive_limit(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate(
                {"type": "first", "search_type": "organizations", "party_id": "o42", "limit": 0}
            )
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate(
                {"type": "first", "search_type": "organizations", "party_id": "o42", "limit": -1}
            )

    def test_first_page_input_rejects_since_after_until(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate(
                {
                    "type": "first",
                    "search_type": "organizations",
                    "party_id": "o42",
                    "since": "2026-02-01",
                    "until": "2026-01-01",
                }
            )

    def test_first_page_input_rejects_an_unknown_search_type(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate(
                {"type": "first", "search_type": "prospects", "party_id": "o42"}
            )

    def test_next_page_input_requires_next_search_type_and_entity_id(self) -> None:
        continuation = {"meeting": {"limit": 10, "offset": 0}}
        with pytest.raises(ValidationError):
            ActivityHistoryNextPageInput.model_validate({"type": "next"})
        with pytest.raises(ValidationError):
            ActivityHistoryNextPageInput.model_validate(
                {"type": "next", "entity_id": "o42", "next": continuation}
            )
        with pytest.raises(ValidationError):
            ActivityHistoryNextPageInput.model_validate(
                {"type": "next", "search_type": "organizations", "next": continuation}
            )
        with pytest.raises(ValidationError):
            ActivityHistoryNextPageInput.model_validate(
                {"type": "next", "search_type": "organizations", "entity_id": "o42"}
            )

    def test_next_page_input_rejects_empty_next_dict(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryNextPageInput.model_validate(
                {
                    "type": "next",
                    "search_type": "organizations",
                    "entity_id": "o42",
                    "next": {},
                }
            )

    def test_next_page_input_rejects_slash_in_entity_id(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryNextPageInput.model_validate(
                {
                    "type": "next",
                    "search_type": "organizations",
                    "entity_id": "o42/evil",
                    "next": {"meeting": {"limit": 10, "offset": 0}},
                }
            )

    def test_next_page_input_rejects_since_after_until(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryNextPageInput.model_validate(
                {
                    "type": "next",
                    "search_type": "organizations",
                    "entity_id": "o42",
                    "next": {
                        "meeting": {
                            "limit": 10,
                            "offset": 0,
                            "since": "2026-02-01",
                            "until": "2026-01-01",
                        }
                    },
                }
            )


class TestPartialFailurePropagates:
    @pytest.mark.asyncio
    @respx.mock
    async def test_one_failing_stream_fails_the_whole_call(self, client: BackstopClient) -> None:

        respx.get(f"{BASE_URL}/organizations/o5").mock(
            return_value=httpx.Response(200, json=_org_document(org_id="o5"))
        )
        _activities_route("organizations", "o5", "meetings").mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "boom"}]})
        )
        _activities_route("organizations", "o5", "notes").mock(
            return_value=httpx.Response(200, json=collection(_activity("n1", "2026-01-01")))
        )

        with pytest.raises(BackstopApiError):
            await get_activity_history(
                ctx_never_elicit(),
                _first(
                    search_type="organizations",
                    party_id="o5",
                    activity_types=["meeting", "note"],
                ),
                client=client,
                activity_history=_SETTINGS,
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_forbidden_stream_is_reported_without_discarding_the_others(
        self, client: BackstopClient
    ) -> None:
        """A 403 on documents must not wipe a successful calls page.

        Backstop names a linked entity the caller cannot operate, not the party being listed.
        """
        respx.get(f"{BASE_URL}/organizations/o5").mock(
            return_value=httpx.Response(200, json=_org_document(org_id="o5"))
        )
        _activities_route("organizations", "o5", "calls").mock(
            return_value=httpx.Response(200, json=collection(_activity("c1", "2026-01-04")))
        )
        _activities_route("organizations", "o5", "documents").mock(
            return_value=httpx.Response(
                403,
                json={
                    "errors": [
                        {
                            "title": "You don't have permission to operate the entity 19759583",
                            "code": "AccessDeniedException",
                        }
                    ]
                },
            )
        )

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _first(
                    search_type="organizations",
                    party_id="o5",
                    activity_types=["call", "document"],
                ),
                client=client,
                activity_history=_SETTINGS,
            ),
            ActivityHistoryResolvedResponse,
        )

        assert _record_keys(result.groups["call"].items) == [("call", "c1")]
        assert result.groups["call"].error is None
        assert result.groups["document"].items == ()
        assert result.groups["document"].next is None
        assert "19759583" in (result.groups["document"].error or "")


class TestDocumentInclusion:
    @pytest.mark.asyncio
    @respx.mock
    async def test_document_appears_when_explicitly_requested(self, client: BackstopClient) -> None:

        respx.get(f"{BASE_URL}/organizations/o9").mock(
            return_value=httpx.Response(200, json=_org_document(org_id="o9"))
        )
        _activities_route("organizations", "o9", "documents").mock(
            return_value=httpx.Response(200, json=collection(_activity("d1", "2026-01-01")))
        )

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _first(
                    search_type="organizations",
                    party_id="o9",
                    activity_types=["document"],
                ),
                client=client,
                activity_history=_SETTINGS,
            ),
            ActivityHistoryResolvedResponse,
        )

        assert set(result.groups) == {"document"}
        assert _record_keys(result.groups["document"].items) == [("document", "d1")]
        first = result.groups["document"].items[0]
        assert isinstance(first, ActivityRecordResponse)
        assert first.title == "Item d1"


class TestWireOmitsNone:
    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_page_omits_date_range(self, client: BackstopClient) -> None:

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_document())
        )
        _activities_route("organizations", "o42", "meetings").mock(
            return_value=httpx.Response(200, json=collection())
        )

        payload = tool_payload(
            await get_activity_history(
                ctx_never_elicit(),
                _first(search_type="organizations", party_id="o42", activity_types=["meeting"]),
                client=client,
                activity_history=_SETTINGS,
            )
        )

        groups = object_dict(payload["groups"])
        meeting_group = object_dict(groups["meeting"])
        assert meeting_group["items"] == []
        assert "date_range" not in meeting_group
        assert "next" not in meeting_group
