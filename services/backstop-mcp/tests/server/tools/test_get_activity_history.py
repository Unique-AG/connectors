"""`get_activity_history`: party resolution, stream fan-out, and grouped-page round-trip.

Each test targets one behaviour from the task: the default-stream fan-out (all five streams,
including `document`), that a resumed call (`type="next"`) skips resolution and only re-fetches
streams present in `next`, that invalid `next` inputs raise pydantic `ValidationError`, and that
one failing stream fails the whole call.
"""

from collections.abc import Callable, Sequence
from datetime import date

import httpx
import pytest
import respx
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopApiError
from backstop_mcp.features.activity_history import (
    ActivityContinuation,
    ActivityHistoryResolvedResponse,
    ActivityRecordResponse,
    ActivityType,
    EmailRecordResponse,
    ResolvedPartyAsOfResponse,
    TimelineRecord,
)
from backstop_mcp.features.data_hygiene import AsOf
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import PartyAmbiguousResponse, PartyCandidateResponse
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools.get_activity_history import (
    ActivityHistoryFirstPageInput,
    ActivityHistoryNextPageInput,
    get_activity_history,
)
from tests.features.party_resolver.helpers import (
    BASE_URL,
    collection,
    ctx_decline,
    ctx_never_elicit,
    resource,
)
from tests.server.tools.helpers import tool_model, tool_model_union, tool_payload

type ConnectUser = Callable[..., object]


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
    next: dict[ActivityType, ActivityContinuation],
) -> ActivityHistoryNextPageInput:
    return ActivityHistoryNextPageInput(
        type="next", search_type=search_type, entity_id=entity_id, next=next
    )


def _record_keys(items: Sequence[TimelineRecord]) -> list[tuple[str, str]]:
    return [(record.type, record.activity_id) for record in items]


class TestFirstCallByTrustedPartyId:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_default_streams_including_document(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-1", "org-bob")  # pyright: ignore[reportGeneralTypeIssues]

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
                ctx_never_elicit(), _first(party_type="organization", party_id="o42")
            ),
            ActivityHistoryResolvedResponse,
        )

        assert result.resolved == ResolvedPartyAsOfResponse(
            id="o42",
            search_type="organizations",
            name="Capstone",
            as_of=AsOf(modified_timestamp="2025-03-01T10:00:00Z", modified_by="ops"),
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
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-2", "org-carol")  # pyright: ignore[reportGeneralTypeIssues]

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
                    party_type="organization",
                    search="Capstone",
                    activity_types=["meeting"],
                ),
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
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-3", "org-dave")  # pyright: ignore[reportGeneralTypeIssues]

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
                ctx_decline(), _first(party_type="organization", search="Capstone")
            ),
            PartyAmbiguousResponse,
        )

        assert result == PartyAmbiguousResponse(
            query="Capstone",
            scope="organizations",
            candidates=[
                PartyCandidateResponse(
                    key="organizations:o1",
                    label="Capstone A",
                    id="o1",
                    search_type="organizations",
                    name="Capstone A",
                ),
                PartyCandidateResponse(
                    key="organizations:o2",
                    label="Capstone B",
                    id="o2",
                    search_type="organizations",
                    name="Capstone B",
                ),
            ],
        )
        assert org_get.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_not_found_search_returns_the_query_it_used(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-4", "person-erin")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = tool_model_union(
            await get_activity_history(
                ctx_never_elicit(), _first(party_type="person", search="Nope")
            ),
            ActivityHistoryResolvedResponse | PartyAmbiguousResponse | NotFoundResponse,
        )

        assert isinstance(result, NotFoundResponse)
        assert result.query == "Nope"
        assert result.scope == "people"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_resolved_collection_when_person_hit_is_a_contact(
        self, connect_user: ConnectUser
    ) -> None:
        """Person quick-search can return contacts; timeline paths must follow search_type."""
        await connect_user("user-ah-contact", "person-contact-hit")  # pyright: ignore[reportGeneralTypeIssues]

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
                _first(party_type="person", search="Jane Contact", activity_types=["meeting"]),
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
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-trusted-contact", "person-trusted-contact")  # pyright: ignore[reportGeneralTypeIssues]

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
                    party_type="person",
                    party_id="c9",
                    search_type="contacts",
                    activity_types=["meeting"],
                ),
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
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-5", "org-frank")  # pyright: ignore[reportGeneralTypeIssues]

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
                    next={"meeting": ActivityContinuation(limit=10, offset=3)},
                ),
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
        self, connect_user: ConnectUser
    ) -> None:
        """Next pages omit ResolvedParty.name; the party GET often has firstName/lastName only."""
        await connect_user("user-ah-5c", "person-gina")  # pyright: ignore[reportGeneralTypeIssues]

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
                    next={"meeting": ActivityContinuation(limit=10, offset=3)},
                ),
            ),
            ActivityHistoryResolvedResponse,
        )

        assert result.resolved == ResolvedPartyAsOfResponse(
            id="p9",
            search_type="people",
            name="Jane Doe",
            as_of=AsOf(modified_timestamp="2025-03-01T10:00:00Z", modified_by="ops"),
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_first_page_email_next_resumes_only_the_email_stream(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-5b", "org-frank2")  # pyright: ignore[reportGeneralTypeIssues]

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
            ctx_never_elicit(), _first(party_type="organization", party_id="o42")
        )
        first_payload = tool_payload(first_result)

        groups = first_payload["groups"]
        assert isinstance(groups, dict)
        meeting_group = groups["meeting"]
        assert isinstance(meeting_group, dict)
        assert "next" not in meeting_group

        email_group = groups["email"]
        assert isinstance(email_group, dict)
        raw_email_next = email_group["next"]
        assert isinstance(raw_email_next, dict)
        assert "since" not in raw_email_next
        assert "until" not in raw_email_next

        resolved = first_payload["resolved"]
        assert isinstance(resolved, dict)
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
        )
        second_payload = tool_payload(second_result)
        second = tool_model(second_result, ActivityHistoryResolvedResponse)
        second_groups = second_payload["groups"]
        assert isinstance(second_groups, dict)
        second_email = second_groups["email"]
        assert isinstance(second_email, dict)
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
    def test_first_page_input_requires_party_type(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate({"type": "first", "party_id": "o42"})

    def test_first_page_input_rejects_non_positive_limit(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate(
                {"type": "first", "party_type": "organization", "party_id": "o42", "limit": 0}
            )
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate(
                {"type": "first", "party_type": "organization", "party_id": "o42", "limit": -1}
            )

    def test_first_page_input_rejects_since_after_until(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate(
                {
                    "type": "first",
                    "party_type": "organization",
                    "party_id": "o42",
                    "since": "2026-02-01",
                    "until": "2026-01-01",
                }
            )

    def test_first_page_input_rejects_search_type_that_does_not_match_party_type(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate(
                {
                    "type": "first",
                    "party_type": "person",
                    "party_id": "c9",
                    "search_type": "organizations",
                }
            )
        with pytest.raises(ValidationError):
            ActivityHistoryFirstPageInput.model_validate(
                {
                    "type": "first",
                    "party_type": "organization",
                    "party_id": "o42",
                    "search_type": "contacts",
                }
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
    async def test_one_failing_stream_fails_the_whole_call(self, connect_user: ConnectUser) -> None:
        await connect_user("user-ah-10", "org-kelly")  # pyright: ignore[reportGeneralTypeIssues]

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
                    party_type="organization",
                    party_id="o5",
                    activity_types=["meeting", "note"],
                ),
            )


class TestDocumentInclusion:
    @pytest.mark.asyncio
    @respx.mock
    async def test_document_appears_when_explicitly_requested(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-11", "org-liam")  # pyright: ignore[reportGeneralTypeIssues]

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
                    party_type="organization",
                    party_id="o9",
                    activity_types=["document"],
                ),
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
    async def test_empty_page_omits_date_range(self, connect_user: ConnectUser) -> None:
        await connect_user("user-ah-wire-omit", "org-wire-omit")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_document())
        )
        _activities_route("organizations", "o42", "meetings").mock(
            return_value=httpx.Response(200, json=collection())
        )

        payload = tool_payload(
            await get_activity_history(
                ctx_never_elicit(),
                _first(party_type="organization", party_id="o42", activity_types=["meeting"]),
            )
        )

        groups = payload["groups"]
        assert isinstance(groups, dict)
        meeting_group = groups["meeting"]
        assert isinstance(meeting_group, dict)
        assert meeting_group["items"] == []
        assert "date_range" not in meeting_group
        assert "next" not in meeting_group
