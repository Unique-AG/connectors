"""Every response body here is synthesised. No name, address or message came from a real tenant."""

from collections.abc import Mapping, Sequence

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphThrottled
from office_365_mcp.tools.outlook_find_recipient import (
    MAX_RESULTS,
    RecipientCandidate,
    find_recipient,
)

_ME: dict[str, object] = {
    "id": "00000000-0000-4000-8000-000000000001",
    "displayName": "Ada Lovelace",
    "mail": "ada@example.invalid",
    "userPrincipalName": "ada@corp.example.invalid",
    "jobTitle": "Analyst",
}

_ORGANIZATION_USER: dict[str, object] = {"class": "Person", "subclass": "OrganizationUser"}


def _person(
    *,
    display_name: str | None = "Tyler Nguyen",
    addresses: Sequence[str] = ("tyler.nguyen@example.invalid",),
    principal_name: str | None = "tyler.nguyen@example.invalid",
    person_type: Mapping[str, object] | None = None,
    job_title: str | None = "Financial Controller",
    department: str | None = "Finance",
) -> dict[str, object]:
    """`relevanceScore` is negative on purpose: that is what `$search` answers with, and no field
    of the answer model may carry it out."""
    return {
        "id": "00000000-0000-4000-8000-00000000000a",
        "displayName": display_name,
        "scoredEmailAddresses": [
            {"address": address, "relevanceScore": -30.5 - index, "selectionLikelihood": "notSure"}
            for index, address in enumerate(addresses)
        ],
        "userPrincipalName": principal_name,
        "personType": dict(person_type) if person_type is not None else _ORGANIZATION_USER,
        "jobTitle": job_title,
        "department": department,
    }


def _recipient(name: str | None, address: str) -> dict[str, object]:
    return {"emailAddress": {"name": name, "address": address}}


def _message(
    *,
    sender: Mapping[str, object] | None = None,
    to: Sequence[Mapping[str, object]] = (),
    cc: Sequence[Mapping[str, object]] = (),
    received_at: str | None = "2026-03-04T09:15:00Z",
) -> dict[str, object]:
    return {
        "id": "AAMkAGI2SYNTHETIC-0001=",
        "from": dict(sender) if sender is not None else None,
        "toRecipients": [dict(one) for one in to],
        "ccRecipients": [dict(one) for one in cc],
        "receivedDateTime": received_at,
    }


@pytest.fixture(autouse=True)
def signed_in(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))


@pytest.fixture
def people(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me/people")


@pytest.fixture
def messages(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me/messages")


def _found(*rows: Mapping[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"value": [dict(row) for row in rows]})


class TestWhatItAsksThePeopleIndexFor:
    async def test_it_sends_the_query_as_one_quoted_search_phrase(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        _ = await find_recipient(client, query="Tyler Nguyen", limit=20)

        assert people.calls.last.request.url.params["$search"] == '"Tyler Nguyen"'

    async def test_a_quote_in_the_query_cannot_close_the_search_phrase(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        """`$search` takes a double-quoted string and Microsoft's only published escaping rule for
        it is a backslash, so a quote in the caller's own text cannot close the string."""
        people.mock(return_value=_found(_person()))

        _ = await find_recipient(client, query='Tyler "the closer"', limit=20)

        search = people.calls.last.request.url.params["$search"]
        assert search == '"Tyler \\"the closer\\""'

    async def test_it_projects_the_fields_it_grades_and_answers_with(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        _ = await find_recipient(client, query="Tyler", limit=7)

        params = people.calls.last.request.url.params
        assert params["$select"].split(",") == [
            "displayName",
            "scoredEmailAddresses",
            "userPrincipalName",
            "personType",
            "jobTitle",
            "department",
        ]
        assert params["$top"] == "7"

    async def test_it_names_both_query_sources_in_plain_ascii(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        """A header copied out of Microsoft's documentation carries typographic hyphens, and Graph
        answers 200 with the directory half of the index missing rather than refusing it."""
        people.mock(return_value=_found(_person()))

        _ = await find_recipient(client, query="Tyler", limit=20)

        sent = people.calls.last.request.headers
        assert sent["X-PeopleQuery-QuerySources"] == "Mailbox,Directory"
        assert all(name.isascii() and value.isascii() for name, value in sent.items())


class TestWhenTheSecondIndexIsReached:
    async def test_an_answered_people_search_never_touches_the_mailbox(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        results = await find_recipient(client, query="Tyler", limit=20)

        assert messages.call_count == 0
        assert [row.source for row in results.candidates] == ["people"]

    async def test_a_fuzzy_only_people_answer_still_counts_as_an_answer(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        """A second index cannot improve a weak answer, only lengthen it."""
        people.mock(return_value=_found(_person()))

        results = await find_recipient(client, query="Tiler", limit=20)

        assert [row.match_kind for row in results.candidates] == ["fuzzy"]
        assert messages.call_count == 0

    async def test_an_empty_people_answer_falls_back_to_the_participants_index(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(
            return_value=_found(
                _message(sender=_recipient("Tyler Nguyen", "tyler.nguyen@example.invalid"))
            )
        )

        results = await find_recipient(client, query="Tyler", limit=20)

        assert messages.call_count == 1
        assert [row.source for row in results.candidates] == ["mailbox"]

    async def test_the_fallback_searches_participants_over_a_fixed_window(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(return_value=_found())

        _ = await find_recipient(client, query="Tyler", limit=5)

        params = messages.calls.last.request.url.params
        assert params["$search"] == '"participants:Tyler"'
        assert params["$select"].split(",") == [
            "from",
            "toRecipients",
            "ccRecipients",
            "receivedDateTime",
        ]
        assert params["$top"] == "50"

    async def test_a_multiword_query_is_quoted_inside_the_participants_term(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(return_value=_found())

        _ = await find_recipient(client, query="Tyler Nguyen", limit=20)

        # This asserted the nested form until the branch review caught it: a value that
        # closes the search string at its third quote and leaves the rest as syntax.
        assert (
            messages.calls.last.request.url.params["$search"] == '"participants:\\"Tyler Nguyen\\""'
        )


class TestHowItGradesARow:
    async def test_the_whole_display_name_is_an_exact_match(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        results = await find_recipient(client, query="tyler nguyen", limit=20)

        assert results.candidates[0].match_kind == "exact"

    async def test_the_address_and_its_local_part_are_both_exact_matches(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        whole = await find_recipient(client, query="tyler.nguyen@example.invalid", limit=20)
        local = await find_recipient(client, query="tyler.nguyen", limit=20)

        assert whole.candidates[0].match_kind == "exact"
        assert local.candidates[0].match_kind == "exact"

    async def test_a_sign_in_name_the_caller_typed_is_an_exact_match(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(
            return_value=_found(
                _person(
                    addresses=("t.nguyen@example.invalid",),
                    principal_name="tyler.nguyen@corp.example.invalid",
                )
            )
        )

        results = await find_recipient(client, query="tyler.nguyen@corp.example.invalid", limit=20)

        assert results.candidates[0].match_kind == "exact"
        assert results.candidates[0].address == "t.nguyen@example.invalid"

    async def test_one_whole_word_of_the_name_is_a_token_match(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        results = await find_recipient(client, query="Tyler", limit=20)

        assert results.candidates[0].match_kind == "token"

    async def test_a_near_miss_microsoft_matched_anyway_is_graded_fuzzy(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        """`$search` is fuzzy by default, so the row Graph is pleased with is not the person the
        user named — and the address on it delivers."""
        people.mock(return_value=_found(_person()))

        results = await find_recipient(client, query="Tiler", limit=20)

        assert results.candidates[0].match_kind == "fuzzy"

    async def test_a_tenant_domain_shared_with_the_sign_in_name_is_not_a_token_match(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        """The sign-in name counts towards `exact` only: its own words are the tenant's domain and,
        for a guest, `EXT`, and none of those is anybody's name."""
        people.mock(
            return_value=_found(
                _person(
                    display_name="Tyler Nguyen",
                    addresses=("tyler.nguyen@example.invalid",),
                    principal_name="tyler.nguyen@corp.example.invalid",
                )
            )
        )

        results = await find_recipient(client, query="corp", limit=20)

        assert results.candidates[0].match_kind == "fuzzy"


class TestWhatItRefusesToDecide:
    async def test_two_rows_sharing_the_best_grade_are_ambiguous(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(
            return_value=_found(
                _person(addresses=("tyler.nguyen@example.invalid",)),
                _person(addresses=("tyler.nguyen@partner.invalid",), department="Sales"),
            )
        )

        results = await find_recipient(client, query="Tyler Nguyen", limit=20)

        assert [row.match_kind for row in results.candidates] == ["exact", "exact"]
        assert results.ambiguous is True

    async def test_one_clear_best_row_is_not_ambiguous(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(
            return_value=_found(
                _person(display_name="Tyler Nguyen"),
                _person(display_name="Tiler Nguyenn", addresses=("t.n@example.invalid",)),
            )
        )

        results = await find_recipient(client, query="Tyler Nguyen", limit=20)

        assert results.ambiguous is False

    async def test_candidates_come_back_strongest_grade_first(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(
            return_value=_found(
                _person(display_name="Tiler Nguyenn", addresses=("t.n@example.invalid",)),
                _person(display_name="Tyler Nguyen"),
            )
        )

        results = await find_recipient(client, query="Tyler Nguyen", limit=20)

        assert [row.match_kind for row in results.candidates] == ["exact", "fuzzy"]

    async def test_a_lone_fuzzy_row_is_not_called_ambiguous(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        results = await find_recipient(client, query="Tiler", limit=20)

        assert results.ambiguous is False


class TestTheAddressItAnswersWith:
    async def test_a_guest_is_answered_at_their_address_and_never_their_sign_in_name(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        """A sign-in name carrying `#EXT#` bounces; the address beside it delivers."""
        people.mock(
            return_value=_found(
                _person(
                    display_name="Grace Hopper",
                    addresses=("grace@fabrikam.invalid",),
                    principal_name="grace_fabrikam.invalid#EXT#@example.invalid",
                )
            )
        )

        results = await find_recipient(client, query="Grace Hopper", limit=20)

        assert results.candidates[0].address == "grace@fabrikam.invalid"
        assert results.candidates[0].external is True

    async def test_a_person_graph_gave_no_address_for_is_dropped(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person(addresses=()), _person()))

        results = await find_recipient(client, query="Tyler Nguyen", limit=20)

        assert [row.address for row in results.candidates] == ["tyler.nguyen@example.invalid"]

    async def test_the_first_address_listed_is_the_one_answered_with(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(
            return_value=_found(
                _person(addresses=("tyler.nguyen@example.invalid", "tn@example.invalid"))
            )
        )

        results = await find_recipient(client, query="Tyler", limit=20)

        assert [row.address for row in results.candidates] == ["tyler.nguyen@example.invalid"]


class TestWhatIsNeverInTheAnswer:
    def test_no_field_of_a_candidate_carries_a_relevance_score(self) -> None:
        """Microsoft documents the score as relative to the rest of the same response, and `$search`
        answers with it negative. A model shown a score ranks on it."""
        assert not [name for name in RecipientCandidate.model_fields if "relevance" in name]
        assert not [name for name in RecipientCandidate.model_fields if "score" in name]

    async def test_a_scored_payload_carries_no_score_out(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        results = await find_recipient(client, query="Tyler", limit=20)

        assert "relevance" not in results.model_dump_json().casefold()


class TestWhatEachRowSaysAboutItself:
    async def test_a_people_row_reports_the_directory_facts_it_was_given(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        row = (await find_recipient(client, query="Tyler", limit=20)).candidates[0]

        assert row.display_name == "Tyler Nguyen"
        assert row.job_title == "Financial Controller"
        assert row.department == "Finance"
        assert row.kind == "person"
        assert row.source == "people"
        assert row.ever_corresponded is False

    async def test_an_address_inside_the_users_own_domain_is_not_external(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        row = (await find_recipient(client, query="Tyler", limit=20)).candidates[0]

        assert row.external is False

    @pytest.mark.parametrize(
        ("person_type", "expected"),
        [
            ({"class": "Person", "subclass": "OrganizationUser"}, "person"),
            ({"class": "Group", "subclass": "UnifiedGroup"}, "group"),
            ({"class": "Person", "subclass": "Room"}, "room"),
            ({"class": "Person", "subclass": "Equipment"}, "room"),
            ({"class": "unknownFutureValue", "subclass": None}, None),
        ],
    )
    async def test_the_person_type_becomes_one_word(
        self,
        client: GraphServiceClient,
        people: respx.Route,
        person_type: dict[str, object],
        expected: str | None,
    ) -> None:
        people.mock(return_value=_found(_person(person_type=person_type)))

        row = (await find_recipient(client, query="Tyler", limit=20)).candidates[0]

        assert row.kind == expected

    async def test_an_external_verdict_needs_a_domain_on_both_sides(
        self, client: GraphServiceClient, graph: respx.MockRouter, people: respx.Route
    ) -> None:
        graph.get("/me").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "00000000-0000-4000-8000-000000000001",
                    "mail": None,
                    "displayName": "Ada Lovelace",
                    "userPrincipalName": None,
                    "jobTitle": None,
                },
            )
        )
        people.mock(return_value=_found(_person()))

        row = (await find_recipient(client, query="Tyler", limit=20)).candidates[0]

        assert row.external is None


class TestWhatTheMailboxFallbackAnswers:
    async def test_a_mailbox_row_is_marked_as_one_and_as_correspondence(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(
            return_value=_found(
                _message(sender=_recipient("Tyler Nguyen", "tyler.nguyen@example.invalid"))
            )
        )

        row = (await find_recipient(client, query="Tyler", limit=20)).candidates[0]

        assert row.source == "mailbox"
        assert row.ever_corresponded is True
        assert row.kind is None
        assert row.job_title is None
        assert row.department is None

    async def test_it_reads_the_sender_and_both_recipient_collections(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(
            return_value=_found(
                _message(sender=_recipient("Tyler Nguyen", "tyler.nguyen@example.invalid")),
                _message(
                    sender=_recipient("Ada Lovelace", "ada@example.invalid"),
                    to=[_recipient("Mai Nguyen", "mai.nguyen@example.invalid")],
                    cc=[_recipient("Bo Nguyen", "bo.nguyen@example.invalid")],
                ),
            )
        )

        results = await find_recipient(client, query="Nguyen", limit=20)

        assert sorted(row.address for row in results.candidates) == [
            "bo.nguyen@example.invalid",
            "mai.nguyen@example.invalid",
            "tyler.nguyen@example.invalid",
        ]

    async def test_the_signed_in_user_is_never_a_candidate(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(
            return_value=_found(_message(sender=_recipient("Ada Lovelace", "ada@example.invalid")))
        )

        results = await find_recipient(client, query="Ada", limit=20)

        assert results.candidates == []
        assert results.outcome == "no_match"

    async def test_a_bystander_on_a_matched_message_is_dropped(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        """`participants` matches whole messages, so everyone copied on one arrives with the person
        actually asked for."""
        people.mock(return_value=_found())
        messages.mock(
            return_value=_found(
                _message(
                    sender=_recipient("Tyler Nguyen", "tyler.nguyen@example.invalid"),
                    to=[_recipient("Bob Vance", "bob@vance.invalid")],
                )
            )
        )

        results = await find_recipient(client, query="Tyler", limit=20)

        assert [row.address for row in results.candidates] == ["tyler.nguyen@example.invalid"]

    async def test_one_address_seen_on_many_messages_is_one_candidate(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(
            return_value=_found(
                _message(
                    sender=_recipient("Tyler", "tyler.nguyen@example.invalid"),
                    received_at="2026-03-01T09:00:00Z",
                ),
                _message(
                    sender=_recipient("Tyler Nguyen", "tyler.nguyen@example.invalid"),
                    received_at="2026-03-04T09:00:00Z",
                ),
            )
        )

        results = await find_recipient(client, query="Tyler Nguyen", limit=20)

        assert len(results.candidates) == 1
        assert results.candidates[0].match_kind == "exact"

    async def test_rows_of_one_grade_come_back_most_recently_seen_first(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(
            return_value=_found(
                _message(
                    sender=_recipient("Tyler Nguyen", "tyler.nguyen@example.invalid"),
                    received_at="2026-03-01T09:00:00Z",
                ),
                _message(
                    sender=_recipient("Mai Nguyen", "mai.nguyen@example.invalid"),
                    received_at="2026-03-04T09:00:00Z",
                ),
            )
        )

        results = await find_recipient(client, query="Nguyen", limit=20)

        assert [row.address for row in results.candidates] == [
            "mai.nguyen@example.invalid",
            "tyler.nguyen@example.invalid",
        ]

    async def test_the_callers_window_bounds_the_fallback_too(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(
            return_value=_found(
                _message(
                    sender=_recipient("Tyler Nguyen", "tyler.nguyen@example.invalid"),
                    to=[_recipient("Mai Nguyen", "mai.nguyen@example.invalid")],
                )
            )
        )

        results = await find_recipient(client, query="Nguyen", limit=1)

        assert len(results.candidates) == 1

    async def test_a_display_name_a_sender_chose_still_grades_against_the_query(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        """A sender writes their own display name, so this row is one person's name beside another
        person's address. It is answered, marked `mailbox`, and never silently preferred."""
        people.mock(return_value=_found())
        messages.mock(
            return_value=_found(
                _message(sender=_recipient("Tyler Nguyen", "not-tyler@partner.invalid"))
            )
        )

        row = (await find_recipient(client, query="Tyler Nguyen", limit=20)).candidates[0]

        assert row.match_kind == "exact"
        assert row.address == "not-tyler@partner.invalid"
        assert row.source == "mailbox"


class TestWhenNobodyMatches:
    async def test_an_empty_answer_is_a_typed_outcome_carrying_the_query(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(return_value=_found())

        results = await find_recipient(client, query="  Tyler  Nguyen ", limit=20)

        assert results.outcome == "no_match"
        assert results.query == "  Tyler  Nguyen "
        assert results.candidates == []
        assert results.ambiguous is False

    async def test_an_answered_search_says_so(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=_found(_person()))

        results = await find_recipient(client, query="Tyler", limit=20)

        assert results.outcome == "match"


class TestWhatItRefuses:
    async def test_a_query_with_no_word_in_it_is_refused_before_graph_is_called(
        self, client: GraphServiceClient, signed_in: respx.Route, people: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="carries no word"):
            _ = await find_recipient(client, query="  ", limit=20)

        assert signed_in.call_count == 0
        assert people.call_count == 0

    @pytest.mark.parametrize("limit", [0, MAX_RESULTS + 1])
    async def test_a_window_outside_the_schema_is_an_assertion(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await find_recipient(client, query="Tyler", limit=limit)


class TestWhatAGraphFailureBecomes:
    async def test_a_refused_people_search_is_a_forbidden(
        self, client: GraphServiceClient, people: respx.Route
    ) -> None:
        people.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await find_recipient(client, query="Tyler", limit=20)

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_fallback_is_a_throttling_and_not_an_outage(
        self, client: GraphServiceClient, people: respx.Route, messages: respx.Route
    ) -> None:
        people.mock(return_value=_found())
        messages.mock(return_value=httpx.Response(429, headers={"Retry-After": "12"}))

        with pytest.raises(GraphThrottled):
            _ = await find_recipient(client, query="Tyler", limit=20)
