"""`get_activity_history`: party resolution, stream fan-out, and cursor round-trip.

Each test targets one behaviour from the task: the default-stream fan-out (and that `document`
is excluded from it), that a resumed call (`type="next"`) skips resolution and only re-fetches
streams the cursor says are still open, that a malformed cursor degrades to a structured
`tool_error` rather than an unhandled exception, that one failing stream fails the whole call,
and the person/organization hygiene-decoration split.
"""

from collections.abc import Callable
from datetime import date

import httpx
import pytest
import respx
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopApiError
from backstop_mcp.features.activity_history import (
    ActivityHistoryResolvedResponse,
    ActivityRecordResponse,
    EmailRecordResponse,
    encode_cursor,
)
from backstop_mcp.features.data_hygiene import AsOf
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    PartyCandidateResponse,
    ResolvedPartyResponse,
)
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools.get_activity_history import (
    ActivityHistoryFirstPageInput,
    ActivityHistoryNextPageInput,
    get_activity_history,
)
from tests.features.data_hygiene.helpers import (
    FORMER_MIRROR_TYPE,
    FORMER_TYPE,
    person_org,
    relationship_types,
)
from tests.features.party_resolver.helpers import (
    BASE_URL,
    collection,
    ctx_decline,
    ctx_never_elicit,
    resource,
)
from tests.server.tools.helpers import tool_model, tool_model_union

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


def _org_document_with_former_employee(
    *, org_id: str = "o42", person_id: str = "p1", name: str = "Capstone"
) -> dict[str, object]:
    """Organization GET with a mirror former-employee relationship side-loaded."""
    relationship = person_org(
        "er0",
        type_id=FORMER_MIRROR_TYPE,
        source_type="organizations",
        source_id=org_id,
        dest_type="people",
        dest_id=person_id,
    )
    types = relationship_types(FORMER_MIRROR_TYPE)
    return {
        "data": {
            "type": "organizations",
            "id": org_id,
            "attributes": {
                "name": name,
                "modifiedTimestamp": "2025-03-01T10:00:00Z",
                "modifiedBy": "ops",
            },
            "relationships": {
                "entityRelationships": {
                    "data": [{"type": "entity-relationships", "id": relationship["id"]}]
                }
            },
        },
        "included": [relationship, *types],
    }


def _person_document(
    *type_ids: str, person_id: str = "p9", name: str = "Jane Doe"
) -> dict[str, object]:
    relationships = [
        person_org(f"er{index}", type_id=type_id, source_id=person_id)
        for index, type_id in enumerate(type_ids)
    ]
    types = relationship_types(*dict.fromkeys(type_ids))
    return {
        "data": {
            "type": "people",
            "id": person_id,
            "attributes": {
                "name": name,
                "modifiedTimestamp": "2023-01-01T00:00:00Z",
                "modifiedBy": "crm-admin",
            },
            "relationships": {
                "entityRelationships": {
                    "data": [
                        {"type": "entity-relationships", "id": item["id"]} for item in relationships
                    ]
                }
            },
        },
        "included": [*relationships, *types],
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


def _next(*, next_cursor: str) -> ActivityHistoryNextPageInput:
    return ActivityHistoryNextPageInput(type="next", next_cursor=next_cursor)


def _record_keys(
    records: list[ActivityRecordResponse | EmailRecordResponse],
) -> list[tuple[str, str]]:
    return [(record.type, record.activity_id) for record in records]


class TestFirstCallByTrustedPartyId:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_default_streams_newest_first_excluding_document(
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

        assert result.resolved == ResolvedPartyResponse(
            id="o42", search_type="organizations", name="Capstone"
        )
        assert result.employments == []
        assert result.as_of == AsOf(modified_timestamp="2025-03-01T10:00:00Z", modified_by="ops")
        assert documents.call_count == 0
        assert _record_keys(result.records) == [
            *[("email", f"e{i}") for i in range(10)],
            ("meeting", "m1"),
            ("call", "c1"),
            ("note", "n1"),
        ]
        assert all(isinstance(record, EmailRecordResponse) for record in result.records[:10])
        assert all(isinstance(record, ActivityRecordResponse) for record in result.records[10:])
        assert result.records[10].occurred_at == date(2026, 1, 5)
        # A full email page leaves the stream open — opaque cursor for the next call.
        assert result.next_cursor is not None


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
        assert _record_keys(result.records) == [("meeting", "m1")]
        first = result.records[0]
        assert isinstance(first, ActivityRecordResponse)
        assert first.title == "Item m1"
        # Short page → stream exhausted → no next page.
        assert result.next_cursor is None

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
                    key="o1",
                    label="Capstone A",
                    id="o1",
                    search_type="organizations",
                    name="Capstone A",
                ),
                PartyCandidateResponse(
                    key="o2",
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


class TestResumedCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_resolution_and_only_refetches_open_streams(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-5", "org-frank")  # pyright: ignore[reportGeneralTypeIssues]

        # Fixture cursor: meeting still open at offset 3; note already exhausted (absent).
        cursor = encode_cursor(
            segment="organizations",
            entity_id="o42",
            limit=10,
            activity_types=["meeting", "note"],
            since=None,
            until=None,
            consumed={"meeting": 3},
        )
        assert cursor is not None

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
            await get_activity_history(ctx_never_elicit(), _next(next_cursor=cursor)),
            ActivityHistoryResolvedResponse,
        )

        assert quick.call_count == 0
        assert notes.call_count == 0
        assert meetings.call_count == 1
        assert result.resolved.id == "o42"
        assert result.resolved.search_type == "organizations"
        assert _record_keys(result.records) == [("meeting", "m4")]
        assert result.next_cursor is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_opaque_cursor_from_first_page_resumes_open_email_stream(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-5b", "org-frank2")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_document())
        )
        for activity_type, item in (
            ("meetings", _activity("m1", "2026-01-05")),
            ("calls", _activity("c1", "2026-01-04")),
            ("notes", _activity("n1", "2026-01-03")),
        ):
            _activities_route("organizations", "o42", activity_type).mock(
                return_value=httpx.Response(200, json=collection(item))
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

        first = tool_model(
            await get_activity_history(
                ctx_never_elicit(), _first(party_type="organization", party_id="o42")
            ),
            ActivityHistoryResolvedResponse,
        )
        assert first.next_cursor is not None

        second = tool_model(
            await get_activity_history(ctx_never_elicit(), _next(next_cursor=first.next_cursor)),
            ActivityHistoryResolvedResponse,
        )

        assert emails.call_count == 2
        assert _record_keys(second.records) == [("email", "e10")]
        assert second.next_cursor is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_cursor_returns_tool_error_not_an_exception(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ah-6", "org-grace")  # pyright: ignore[reportGeneralTypeIssues]

        result = await get_activity_history(
            ctx_never_elicit(), _next(next_cursor="not-a-valid-cursor-at-all-!!!")
        )

        assert result.isError is True


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

    def test_next_page_input_requires_next_cursor(self) -> None:
        with pytest.raises(ValidationError):
            ActivityHistoryNextPageInput.model_validate({"type": "next"})


class TestHygieneDecoration:
    @pytest.mark.asyncio
    @respx.mock
    async def test_person_party_gets_employments(self, connect_user: ConnectUser) -> None:
        await connect_user("user-ah-8", "person-ivan")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/people/p9").mock(
            return_value=httpx.Response(200, json=_person_document(FORMER_TYPE))
        )
        respx.get(f"{BASE_URL}/entity-relationship-types").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )
        _activities_route("people", "p9", "meetings").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _first(party_type="person", party_id="p9", activity_types=["meeting"]),
            ),
            ActivityHistoryResolvedResponse,
        )

        assert len(result.employments) == 1
        assert result.employments[0].status == "former"
        assert result.employments[0].organization_id == "o1"
        assert result.employments[0].person_id == "p9"

    @pytest.mark.asyncio
    @respx.mock
    async def test_organization_party_gets_employments(self, connect_user: ConnectUser) -> None:
        await connect_user("user-ah-9", "org-jill")  # pyright: ignore[reportGeneralTypeIssues]

        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=_org_document_with_former_employee())
        )
        _activities_route("organizations", "o42", "meetings").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = tool_model(
            await get_activity_history(
                ctx_never_elicit(),
                _first(
                    party_type="organization",
                    party_id="o42",
                    activity_types=["meeting"],
                ),
            ),
            ActivityHistoryResolvedResponse,
        )

        assert len(result.employments) == 1
        assert result.employments[0].status == "former"
        assert result.employments[0].person_id == "p1"
        assert result.employments[0].organization_id == "o42"


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

        assert _record_keys(result.records) == [("document", "d1")]
        first = result.records[0]
        assert isinstance(first, ActivityRecordResponse)
        assert first.title == "Item d1"
