"""`outlook_list_mail`: the query it composes, the folder it answers, what it refuses.

The query is most of this file. Microsoft returns an `InefficientFilter` error for a bad
`$orderby`. That happens when `$orderby` names a property that `$filter` does not name, names in
a different order, or names after an unfiltered property.

So the assertions below pin one construction. Whatever the tool passes to it, the construction
cannot break those rules:
1. `receivedDateTime` is always ordered.
2. `receivedDateTime` is always the first filtered property, whenever `$filter` exists at all.
3. Every term on another property comes strictly after it.

The narrowing arguments are asserted twice over, and on purpose. `unread_only` and `from_address`
each reach `$filter` only beside a date. Alone, either one leaves `$filter` with no ordered
property. The tool also inspects each of them again on the returned rows, because Microsoft
documents that Graph can drop an unsupported filter without a warning. So this file has two
families of test: what goes on the wire, and what the answer holds when the tool does not
trust it.

Every response body here is synthesised. None came from a real mailbox.
"""

from datetime import UTC, date, datetime, timedelta, timezone

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.handles import MailFolderHandle, MailMessageHandle
from office_365_mcp.shared.mail import WellKnownFolder
from office_365_mcp.tools import outlook_list_mail as lister

from .conftest import GRAPH_V1

_INBOX = "/me/mailFolders/inbox"
_INBOX_MESSAGES = f"{_INBOX}/messages"

_PROJECTS_ID = "AQMkADAwSYNTHETIC-projects"
_PROJECTS = f"/me/mailFolders/{_PROJECTS_ID}"
_PROJECTS_MESSAGES = f"{_PROJECTS}/messages"

_FIRST_ID = "AAMkAGI2SYNTHETIC-immutable-0001="
_SECOND_ID = "AAMkAGI2SYNTHETIC-immutable-0002="


def _folder_payload(
    *,
    display_name: str | None = "Inbox",
    total_items: int | None = 412,
    unread_items: int | None = 70,
) -> dict[str, object]:
    return {
        "displayName": display_name,
        "totalItemCount": total_items,
        "unreadItemCount": unread_items,
    }


def _message_payload(
    message_id: str,
    *,
    subject: str = "Invoice 4471",
    received_at: str = "2026-03-04T09:15:00Z",
    is_read: bool | None = False,
    sender: str | None = "bob@vance.invalid",
) -> dict[str, object]:
    return {
        "id": message_id,
        "subject": subject,
        "bodyPreview": "Please find the invoice attached.",
        "from": (
            None if sender is None else {"emailAddress": {"name": "Bob Vance", "address": sender}}
        ),
        "toRecipients": [{"emailAddress": {"name": "Ada", "address": "ada@contoso.invalid"}}],
        "receivedDateTime": received_at,
        "isRead": is_read,
        "hasAttachments": True,
        "parentFolderId": "AQMkADAwSYNTHETIC-folder",
        "webLink": "https://outlook.office365.invalid/owa/?ItemID=synthetic",
    }


def _page(*messages: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(messages)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


@pytest.fixture
def inbox(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_INBOX).mock(return_value=httpx.Response(200, json=_folder_payload()))


@pytest.fixture
def inbox_messages(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_INBOX_MESSAGES).mock(return_value=_page(_message_payload(_FIRST_ID)))


class TestTheQueryItComposes:
    @pytest.mark.usefixtures("inbox_messages")
    async def test_it_reads_the_folder_for_the_counts_graph_gives_away_on_it(
        self, client: GraphServiceClient, inbox: respx.Route
    ) -> None:
        """Microsoft recommends these fields over counting a folder's messages with `$count` and
        `$filter`. Microsoft warns that the count can add significant delay."""
        _ = await lister.list_mail(client, limit=25)

        assert inbox.call_count == 1
        params = inbox.calls.last.request.url.params
        assert params["$select"].split(",") == [
            "displayName",
            "totalItemCount",
            "unreadItemCount",
        ]
        assert "$count" not in params

    @pytest.mark.usefixtures("inbox")
    async def test_it_asks_for_the_shared_summary_fields_and_the_callers_window(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        _ = await lister.list_mail(client, limit=7)

        params = inbox_messages.calls.last.request.url.params
        assert params["$top"] == "7"
        assert "bodyPreview" in params["$select"]

    @pytest.mark.usefixtures("inbox")
    async def test_receipt_order_is_asked_for_with_no_other_argument_given(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        _ = await lister.list_mail(client, limit=25)

        assert inbox_messages.calls.last.request.url.params["$orderby"] == "receivedDateTime desc"

    @pytest.mark.usefixtures("inbox")
    @pytest.mark.parametrize("unread_only", [False, True])
    @pytest.mark.parametrize("received_after", [None, date(2026, 3, 4)])
    @pytest.mark.parametrize("received_before", [None, date(2026, 3, 31)])
    async def test_receipt_order_is_unconditional(
        self,
        client: GraphServiceClient,
        inbox_messages: respx.Route,
        unread_only: bool,
        received_after: date | None,
        received_before: date | None,
    ) -> None:
        """A promise of "newest first" that holds for only some arguments is worse than no
        promise at all."""
        _ = await lister.list_mail(
            client,
            unread_only=unread_only,
            received_after=received_after,
            received_before=received_before,
            limit=25,
        )

        assert inbox_messages.calls.last.request.url.params["$orderby"] == "receivedDateTime desc"

    @pytest.mark.usefixtures("inbox")
    @pytest.mark.parametrize("received_after", [None, date(2026, 3, 4)])
    @pytest.mark.parametrize("received_before", [None, date(2026, 3, 31)])
    async def test_the_dates_alone_put_nothing_but_dates_in_the_filter(
        self,
        client: GraphServiceClient,
        inbox_messages: respx.Route,
        received_after: date | None,
        received_before: date | None,
    ) -> None:
        """With no narrowing argument beside them, the two bounds form the whole `$filter`: one
        property, named once or twice, and nothing else."""
        _ = await lister.list_mail(
            client, received_after=received_after, received_before=received_before, limit=25
        )

        params = inbox_messages.calls.last.request.url.params
        assert params["$orderby"] == "receivedDateTime desc"
        if received_after is None and received_before is None:
            assert "$filter" not in params
            return
        terms = params["$filter"].split(" and ")
        assert len(terms) == (received_after is not None) + (received_before is not None)
        assert all(term.startswith("receivedDateTime ") for term in terms), params["$filter"]

    @pytest.mark.usefixtures("inbox")
    async def test_no_date_means_no_filter_at_all(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        _ = await lister.list_mail(client, limit=25)

        assert "$filter" not in inbox_messages.calls.last.request.url.params

    @pytest.mark.usefixtures("inbox")
    async def test_a_date_bounds_the_very_property_the_order_is_taken_on(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """This is Microsoft's rule, and it is the reason why this tool has exactly one orderable
        property. Every property in `$orderby` must also be in `$filter`, in the same order, and
        first."""
        _ = await lister.list_mail(client, received_after=date(2026, 3, 4), limit=25)

        params = inbox_messages.calls.last.request.url.params
        assert params["$filter"] == "receivedDateTime ge 2026-03-04T00:00:00Z"
        assert params["$orderby"].split(" ")[0] == params["$filter"].split(" ")[0]

    @pytest.mark.usefixtures("inbox")
    async def test_a_closing_date_bounds_the_day_after_it_so_that_day_is_covered_whole(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """This uses `lt` at the start of the following day. `shared/calendar.py` closes an
        Outlook date window the same way. A `le` on this day's own last instant must pick a
        precision, and it drops whatever arrived after that precise instant."""
        _ = await lister.list_mail(client, received_before=date(2026, 3, 4), limit=25)

        params = inbox_messages.calls.last.request.url.params
        assert params["$filter"] == "receivedDateTime lt 2026-03-05T00:00:00Z"

    @pytest.mark.usefixtures("inbox")
    async def test_two_dates_close_the_window_at_both_ends(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        _ = await lister.list_mail(
            client, received_after=date(2026, 3, 1), received_before=date(2026, 3, 31), limit=25
        )

        assert inbox_messages.calls.last.request.url.params["$filter"] == (
            "receivedDateTime ge 2026-03-01T00:00:00Z and receivedDateTime lt 2026-04-01T00:00:00Z"
        )

    @pytest.mark.usefixtures("inbox")
    async def test_one_date_in_both_bounds_asks_for_that_single_day(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """The bound that both arguments promise is a whole UTC day, so "what came in on Tuesday"
        is that one date, given twice. Two first instants bracket nothing at all."""
        _ = await lister.list_mail(
            client, received_after=date(2026, 3, 4), received_before=date(2026, 3, 4), limit=25
        )

        assert inbox_messages.calls.last.request.url.params["$filter"] == (
            "receivedDateTime ge 2026-03-04T00:00:00Z and receivedDateTime lt 2026-03-05T00:00:00Z"
        )

    @pytest.mark.usefixtures("inbox")
    @pytest.mark.parametrize("received_after", [None, date(2026, 3, 4)])
    @pytest.mark.parametrize("received_before", [None, date(2026, 3, 31)])
    async def test_an_unordered_term_reaches_the_filter_only_beside_a_date(
        self,
        client: GraphServiceClient,
        inbox_messages: respx.Route,
        received_after: date | None,
        received_before: date | None,
    ) -> None:
        """`isRead` is unordered beside an `$orderby` on `receivedDateTime`. With a date term
        present, it is legal, because the third rule asks only that the ordered property come
        first. Alone, it breaks the first rule: `$filter` then names no ordered property at all,
        and Microsoft documents that request as `InefficientFilter`."""
        _ = await lister.list_mail(
            client,
            unread_only=True,
            received_after=received_after,
            received_before=received_before,
            limit=25,
        )

        params = inbox_messages.calls.last.request.url.params
        if received_after is None and received_before is None:
            assert "$filter" not in params, "read state alone cannot carry the query"
        else:
            assert params["$filter"].endswith("and isRead eq false")

    @pytest.mark.usefixtures("inbox")
    @pytest.mark.parametrize("unread_only", [False, True])
    @pytest.mark.parametrize("from_address", [None, "bob@vance.invalid"])
    @pytest.mark.parametrize("received_after", [None, date(2026, 3, 4)])
    @pytest.mark.parametrize("received_before", [None, date(2026, 3, 31)])
    async def test_every_ordered_term_precedes_every_unordered_one(
        self,
        client: GraphServiceClient,
        inbox_messages: respx.Route,
        unread_only: bool,
        from_address: str | None,
        received_after: date | None,
        received_before: date | None,
    ) -> None:
        """This tests Microsoft's third rule over all sixteen argument combinations, not just the
        ones somebody thought to try. The rule: no `receivedDateTime` term can follow a term on
        any other property. A refactor that reorders the conjuncts can turn arguments that are
        each fine on their own into an `InefficientFilter`."""
        _ = await lister.list_mail(
            client,
            unread_only=unread_only,
            from_address=from_address,
            received_after=received_after,
            received_before=received_before,
            limit=25,
        )

        params = inbox_messages.calls.last.request.url.params
        assert params["$orderby"] == "receivedDateTime desc"
        if "$filter" not in params:
            assert received_after is None and received_before is None
            return
        ordered = [
            term.startswith("receivedDateTime ") for term in params["$filter"].split(" and ")
        ]
        assert ordered[0], params["$filter"]
        assert ordered == sorted(ordered, reverse=True), params["$filter"]

    @pytest.mark.usefixtures("inbox")
    async def test_a_moment_bounds_the_second_it_names_rather_than_the_day(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """A named second is exact already, so the upper bound closes with `le` at it rather than
        with `lt` at the next day. Both spellings keep the one promise `shared/window.py` makes:
        the value the caller named is inside the window."""
        _ = await lister.list_mail(
            client,
            received_after=datetime(2026, 3, 4, 9, 0, tzinfo=UTC),
            received_before=datetime(2026, 3, 4, 17, 0, tzinfo=UTC),
            limit=25,
        )

        assert inbox_messages.calls.last.request.url.params["$filter"] == (
            "receivedDateTime ge 2026-03-04T09:00:00Z and receivedDateTime le 2026-03-04T17:00:00Z"
        )

    @pytest.mark.usefixtures("inbox")
    async def test_a_moment_with_no_zone_is_read_as_utc_and_not_as_the_servers_own(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """Otherwise the bound lands in whichever zone the pod runs in: a zone that no caller
        chose and that no answer names."""
        _ = await lister.list_mail(client, received_after=datetime(2026, 3, 4, 9, 0), limit=25)

        assert inbox_messages.calls.last.request.url.params["$filter"] == (
            "receivedDateTime ge 2026-03-04T09:00:00Z"
        )

    @pytest.mark.usefixtures("inbox")
    async def test_a_moment_east_of_utc_is_converted_rather_than_relabelled(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """09:00+02:00 is 07:00 UTC. Stamping `Z` directly on the wall-clock value moves the bound
        two hours. `shared/window.py` documents this as the trap in using `as_utc` alone."""
        _ = await lister.list_mail(
            client,
            received_after=datetime(2026, 3, 4, 9, 0, tzinfo=timezone(timedelta(hours=2))),
            limit=25,
        )

        assert inbox_messages.calls.last.request.url.params["$filter"] == (
            "receivedDateTime ge 2026-03-04T07:00:00Z"
        )

    @pytest.mark.usefixtures("inbox")
    async def test_a_sub_second_bound_keeps_its_precision_on_the_wire(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """Truncating to whole seconds moves both bounds earlier. Both failures are silent. The
        lower bound then lets in mail that the caller excluded. The upper bound then shuts out
        mail that the caller included. `capped` stays false, and nothing says that the tool
        dropped a row."""
        _ = await lister.list_mail(
            client,
            received_after=datetime(2026, 3, 4, 9, 0, 0, 750000, tzinfo=UTC),
            received_before=datetime(2026, 3, 4, 17, 0, 0, 750000, tzinfo=UTC),
            limit=25,
        )

        assert inbox_messages.calls.last.request.url.params["$filter"] == (
            "receivedDateTime ge 2026-03-04T09:00:00.750000Z "
            + "and receivedDateTime le 2026-03-04T17:00:00.750000Z"
        )

    @pytest.mark.usefixtures("inbox")
    async def test_a_whole_second_bound_carries_no_fraction(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """This is the other half of the rule: the tool keeps precision, never adds it. A date
        resolves to midnight, so every date-bounded query still sends the bytes it always did."""
        _ = await lister.list_mail(
            client, received_after=datetime(2026, 3, 4, 9, 0, tzinfo=UTC), limit=25
        )

        assert inbox_messages.calls.last.request.url.params["$filter"] == (
            "receivedDateTime ge 2026-03-04T09:00:00Z"
        )

    @pytest.mark.usefixtures("inbox")
    async def test_a_date_and_a_moment_can_bound_the_same_window(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """The two shapes mix, and each end keeps its own spelling."""
        _ = await lister.list_mail(
            client,
            received_after=date(2026, 3, 1),
            received_before=datetime(2026, 3, 4, 17, 30, tzinfo=UTC),
            limit=25,
        )

        assert inbox_messages.calls.last.request.url.params["$filter"] == (
            "receivedDateTime ge 2026-03-01T00:00:00Z and receivedDateTime le 2026-03-04T17:30:00Z"
        )

    @pytest.mark.usefixtures("inbox")
    async def test_a_sender_is_filtered_on_the_address_graph_documents(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        _ = await lister.list_mail(
            client,
            received_after=date(2026, 3, 4),
            from_address="bob@vance.invalid",
            limit=25,
        )

        assert inbox_messages.calls.last.request.url.params["$filter"] == (
            "receivedDateTime ge 2026-03-04T00:00:00Z "
            + "and from/emailAddress/address eq 'bob@vance.invalid'"
        )

    @pytest.mark.usefixtures("inbox")
    async def test_a_quote_in_an_address_cannot_close_the_literal(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """`o'brien@…` is a legal SMTP address, and an unescaped quote there ends the literal and
        leaves the rest as predicate syntax."""
        _ = await lister.list_mail(
            client,
            received_after=date(2026, 3, 4),
            from_address="o'brien@vance.invalid",
            limit=25,
        )

        sent = inbox_messages.calls.last.request.url.params["$filter"]
        assert sent.endswith("and from/emailAddress/address eq 'o''brien@vance.invalid'")
        assert sent.count("'") % 2 == 0

    @pytest.mark.usefixtures("inbox")
    async def test_a_sender_with_no_date_is_left_out_of_the_query_and_still_narrows_the_rows(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """If the tool puts this term alone in `$filter`, undated, it breaks the first rule. So
        the code relies on the row check instead, which narrows the answer either way."""
        inbox_messages.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _message_payload(_FIRST_ID, sender="bob@vance.invalid"),
                        _message_payload(_SECOND_ID, sender="dana@contoso.invalid"),
                    ]
                },
            )
        )

        answered = await lister.list_mail(client, from_address="bob@vance.invalid", limit=25)

        assert "$filter" not in inbox_messages.calls.last.request.url.params
        assert [row.sender.address for row in answered.messages if row.sender is not None] == [
            "bob@vance.invalid"
        ]

    @pytest.mark.usefixtures("inbox")
    async def test_a_row_graph_returned_against_the_filter_is_still_discarded(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """Microsoft documents that an unsupported filter can fail silently. If Graph drops the
        term, another sender's mail appears in an answer that named one sender. So the tool
        inspects the rows even when the term went out on the wire."""
        inbox_messages.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _message_payload(_FIRST_ID, sender="bob@vance.invalid"),
                        _message_payload(_SECOND_ID, sender="dana@contoso.invalid"),
                    ]
                },
            )
        )

        answered = await lister.list_mail(
            client,
            received_after=date(2026, 3, 4),
            from_address="bob@vance.invalid",
            limit=25,
        )

        assert (
            "from/emailAddress/address" in inbox_messages.calls.last.request.url.params["$filter"]
        )
        assert [row.uri for row in answered.messages] == [MailMessageHandle(_FIRST_ID).uri]

    @pytest.mark.usefixtures("inbox")
    async def test_a_sender_matches_whatever_casing_the_message_carried(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """Exchange echoes the sender's own casing, not the casing that the filter used, and an
        SMTP address is case-insensitive. An exact comparison drops a row that Exchange itself
        considers a match."""
        inbox_messages.mock(
            return_value=httpx.Response(
                200, json={"value": [_message_payload(_FIRST_ID, sender="Bob.Vance@Vance.INVALID")]}
            )
        )

        answered = await lister.list_mail(client, from_address="bob.vance@vance.invalid", limit=25)

        assert len(answered.messages) == 1

    @pytest.mark.usefixtures("inbox")
    async def test_a_row_with_no_sender_is_not_credited_to_the_one_asked_for(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        inbox_messages.mock(
            return_value=httpx.Response(
                200, json={"value": [_message_payload(_FIRST_ID, sender=None)]}
            )
        )

        answered = await lister.list_mail(client, from_address="bob@vance.invalid", limit=25)

        assert answered.messages == []

    @pytest.mark.usefixtures("inbox")
    async def test_the_first_page_is_never_reached_by_skipping(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """Graph's own `$skip` inside an `@odata.nextLink` counts the items that the service
        enumerated, not the ones it handed back. So the tool follows the link whole, and it never
        builds `$skip` here."""
        _ = await lister.list_mail(client, limit=25)

        assert "$skip" not in inbox_messages.calls.last.request.url.params

    @pytest.mark.usefixtures("inbox")
    async def test_the_listing_asks_for_ids_that_outlive_the_message_being_filed(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """This is the same preference that `outlook_read_mail` sends on the way in. Without it,
        these handles are `RestId`s, and a `RestId` dies the moment an inbox rule files the
        message."""
        _ = await lister.list_mail(client, limit=25)

        assert 'IdType="ImmutableId"' in inbox_messages.calls.last.request.headers["Prefer"]

    @pytest.mark.usefixtures("inbox")
    async def test_the_preference_is_supplied_again_for_every_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`PageIterator` starts from an empty header collection. So a page that the tool fetches
        without the preference answers in the other id space, and it mints handles that fail
        with a 404."""
        cursor = graph.get(_INBOX_MESSAGES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_message_payload(_SECOND_ID))
        )
        graph.get(_INBOX_MESSAGES).mock(
            return_value=_page(
                _message_payload(_FIRST_ID),
                next_link=f"{GRAPH_V1}{_INBOX_MESSAGES}?$skiptoken=second",
            )
        )

        _ = await lister.list_mail(client, limit=25)

        assert 'IdType="ImmutableId"' in cursor.calls.last.request.headers["Prefer"]

    async def test_the_preference_does_not_leak_onto_another_request(
        self, client: GraphServiceClient, inbox: respx.Route, inbox_messages: respx.Route
    ) -> None:
        """Kiota's `RequestConfiguration.headers` default is one collection, shared across the
        whole process. So a preference added to it reaches the folder read of every later call."""
        _ = await lister.list_mail(client, limit=25)
        _ = await lister.list_mail(client, limit=25)

        assert inbox.call_count == 2
        assert "Prefer" not in inbox.calls.last.request.headers
        assert inbox_messages.call_count == 2


class TestTheFolderItAddresses:
    @pytest.mark.usefixtures("inbox", "inbox_messages")
    @pytest.mark.parametrize("folder", ["inbox", "sentitems", "junkemail"])
    async def test_a_well_known_name_reaches_that_folder_by_name(
        self, client: GraphServiceClient, graph: respx.MockRouter, folder: WellKnownFolder
    ) -> None:
        """The names are locale-independent, so the tool sends them exactly as Microsoft spells
        them, rather than resolving them to an id first."""
        named = graph.get(f"/me/mailFolders/{folder}").mock(
            return_value=httpx.Response(200, json=_folder_payload())
        )
        messages = graph.get(f"/me/mailFolders/{folder}/messages").mock(
            return_value=_page(_message_payload(_FIRST_ID))
        )

        _ = await lister.list_mail(client, folder=folder, limit=25)

        assert named.call_count == 1
        assert messages.call_count == 1

    async def test_a_folder_handle_reaches_the_folder_it_addresses(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        inbox: respx.Route,
        inbox_messages: respx.Route,
    ) -> None:
        projects = graph.get(_PROJECTS).mock(
            return_value=httpx.Response(200, json=_folder_payload(display_name="Projects"))
        )
        projects_messages = graph.get(_PROJECTS_MESSAGES).mock(
            return_value=_page(_message_payload(_FIRST_ID))
        )

        answer = await lister.list_mail(
            client, folder_ref=MailFolderHandle(_PROJECTS_ID).uri, limit=25
        )

        assert projects.call_count == 1
        assert projects_messages.call_count == 1
        assert inbox.call_count == 0, "a handle addresses one folder, not the default one"
        assert inbox_messages.call_count == 0
        assert answer.folder_name == "Projects"


class TestWhatItAnswers:
    @pytest.mark.usefixtures("inbox_messages")
    async def test_the_folders_own_counts_come_back_with_the_rows(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_INBOX).mock(
            return_value=httpx.Response(
                200,
                json=_folder_payload(display_name="Inbox", total_items=412, unread_items=70),
            )
        )

        answer = await lister.list_mail(client, limit=25)

        assert answer.folder_name == "Inbox"
        assert answer.total_items == 412
        assert answer.unread_items == 70

    @pytest.mark.usefixtures("inbox_messages")
    async def test_a_folder_graph_reported_no_counts_for_is_still_listed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A count is a number or nothing, never a zero this tool invented."""
        graph.get(_INBOX).mock(
            return_value=httpx.Response(
                200,
                json=_folder_payload(display_name=None, total_items=None, unread_items=None),
            )
        )

        answer = await lister.list_mail(client, limit=25)

        assert answer.folder_name is None
        assert answer.total_items is None
        assert answer.unread_items is None
        assert len(answer.messages) == 1

    @pytest.mark.usefixtures("inbox")
    async def test_each_row_carries_the_handle_that_reads_the_message(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        inbox_messages.mock(
            return_value=_page(_message_payload(_FIRST_ID), _message_payload(_SECOND_ID))
        )

        answer = await lister.list_mail(client, limit=25)

        assert [message.uri for message in answer.messages] == [
            MailMessageHandle(_FIRST_ID).uri,
            MailMessageHandle(_SECOND_ID).uri,
        ]

    @pytest.mark.usefixtures("inbox", "inbox_messages")
    async def test_it_reports_the_fields_a_model_triages_on(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_mail(client, limit=25)

        row = answer.messages[0]
        assert row.subject == "Invoice 4471"
        assert row.preview == "Please find the invoice attached."
        assert row.sender is not None
        assert row.sender.address == "bob@vance.invalid"
        assert [address.address for address in row.to] == ["ada@contoso.invalid"]
        assert row.received_at is not None
        assert row.is_read is False
        assert row.has_attachments is True

    @pytest.mark.usefixtures("inbox")
    async def test_the_order_graph_returned_is_the_order_answered(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        inbox_messages.mock(
            return_value=_page(
                _message_payload(_FIRST_ID, received_at="2026-03-04T09:15:00Z"),
                _message_payload(_SECOND_ID, received_at="2026-03-01T08:00:00Z"),
            )
        )

        answer = await lister.list_mail(client, limit=25)

        assert [message.received_at for message in answer.messages] == [
            "2026-03-04T09:15:00+00:00",
            "2026-03-01T08:00:00+00:00",
        ]

    @pytest.mark.usefixtures("inbox")
    async def test_unread_only_keeps_the_unread_rows_and_drops_the_rest(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        inbox_messages.mock(
            return_value=_page(
                _message_payload(_FIRST_ID, is_read=True),
                _message_payload(_SECOND_ID, is_read=False),
            )
        )

        answer = await lister.list_mail(client, unread_only=True, limit=25)

        assert [message.uri for message in answer.messages] == [MailMessageHandle(_SECOND_ID).uri]

    @pytest.mark.usefixtures("inbox")
    async def test_a_row_graph_said_nothing_about_is_not_counted_as_unread(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        inbox_messages.mock(return_value=_page(_message_payload(_FIRST_ID, is_read=None)))

        answer = await lister.list_mail(client, unread_only=True, limit=25)

        assert answer.messages == []

    @pytest.mark.usefixtures("inbox")
    async def test_the_pages_of_a_folder_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The test registers the cursor route before the bare one. respx matches routes in
        registration order, so the bare path also matches a `$skiptoken` request and answers
        every page."""
        graph.get(_INBOX_MESSAGES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_message_payload(_SECOND_ID))
        )
        graph.get(_INBOX_MESSAGES).mock(
            return_value=_page(
                _message_payload(_FIRST_ID),
                next_link=f"{GRAPH_V1}{_INBOX_MESSAGES}?$skiptoken=second",
            )
        )

        answer = await lister.list_mail(client, limit=25)

        assert [message.uri for message in answer.messages] == [
            MailMessageHandle(_FIRST_ID).uri,
            MailMessageHandle(_SECOND_ID).uri,
        ]
        assert answer.capped is False, "the walk reached the end of the folder"

    @pytest.mark.usefixtures("inbox")
    async def test_a_cap_that_left_more_of_the_folder_on_offer_says_capped(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        inbox_messages.mock(
            return_value=_page(_message_payload(_FIRST_ID), _message_payload(_SECOND_ID))
        )

        answer = await lister.list_mail(client, limit=1)

        assert [message.uri for message in answer.messages] == [MailMessageHandle(_FIRST_ID).uri]
        assert answer.capped is True

    @pytest.mark.usefixtures("inbox")
    async def test_a_window_filled_exactly_by_the_end_of_the_folder_is_not_capped(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """`capped` means a cap stopped the walk with more still on offer, never that the answer
        was short."""
        inbox_messages.mock(
            return_value=_page(_message_payload(_FIRST_ID), _message_payload(_SECOND_ID))
        )

        answer = await lister.list_mail(client, limit=2)

        assert len(answer.messages) == 2
        assert answer.capped is False

    @pytest.mark.usefixtures("inbox")
    async def test_an_empty_folder_answers_no_rows_and_no_cap(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        inbox_messages.mock(return_value=_page())

        answer = await lister.list_mail(client, limit=25)

        assert answer.messages == []
        assert answer.capped is False, "an empty folder is the whole of it, not a cap"


class TestWhatItRefuses:
    @pytest.mark.parametrize("folder", ["sentitems", "archive"])
    async def test_a_folder_and_a_folder_ref_together_never_reach_graph(
        self,
        client: GraphServiceClient,
        inbox: respx.Route,
        graph: respx.MockRouter,
        folder: WellKnownFolder,
    ) -> None:
        """One call lists one folder. If the tool silently picks one of the two on its own, it
        lists a folder that nobody asked for."""
        named = graph.get(f"/me/mailFolders/{folder}")

        with pytest.raises(ToolError, match="alternatives"):
            _ = await lister.list_mail(
                client, folder=folder, folder_ref=MailFolderHandle(_PROJECTS_ID).uri, limit=25
            )

        assert inbox.call_count == 0
        assert named.call_count == 0

    @pytest.mark.parametrize(
        "folder_ref",
        [
            "Projects",
            "inbox",
            _PROJECTS_ID,
            "outlook:///folders/",
            MailMessageHandle(_FIRST_ID).uri,
        ],
    )
    async def test_a_folder_ref_that_is_not_a_folder_handle_never_reaches_graph(
        self, client: GraphServiceClient, inbox: respx.Route, folder_ref: str
    ) -> None:
        with pytest.raises(ToolError, match="folder handle"):
            _ = await lister.list_mail(client, folder_ref=folder_ref, limit=25)

        assert inbox.call_count == 0

    async def test_the_refusal_names_the_argument_that_takes_a_well_known_name(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="`folder`"):
            _ = await lister.list_mail(client, folder_ref="Projects", limit=25)

    @pytest.mark.parametrize("limit", [0, lister.MAX_RESULTS + 1])
    async def test_a_window_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.list_mail(client, limit=limit)

    async def test_a_backwards_window_is_caught_across_the_two_shapes(
        self, client: GraphServiceClient, inbox: respx.Route
    ) -> None:
        """Python refuses to order a date against a moment, so the tool compares the bounds as
        instants. A direct comparison between them raises `TypeError` instead of a clear
        refusal."""
        with pytest.raises(ToolError, match="backwards"):
            _ = await lister.list_mail(
                client,
                received_after=datetime(2026, 3, 31, 9, 0, tzinfo=UTC),
                received_before=date(2026, 3, 1),
                limit=25,
            )

        assert inbox.call_count == 0

    @pytest.mark.usefixtures("inbox", "inbox_messages")
    async def test_two_moments_naming_one_instant_are_not_backwards(
        self, client: GraphServiceClient
    ) -> None:
        """Both bounds include what they name, so one instant in both is that instant — the
        narrowest window there is, and still a window."""
        moment = datetime(2026, 3, 4, 9, 15, tzinfo=UTC)

        answered = await lister.list_mail(
            client, received_after=moment, received_before=moment, limit=25
        )

        assert answered.messages != []

    async def test_a_window_that_runs_backwards_never_reaches_graph(
        self, client: GraphServiceClient, inbox: respx.Route
    ) -> None:
        """Graph answers a backwards window with an empty page, which is the same answer as "no
        mail in that window". Only one of the two is worth reporting, so the refusal happens
        here."""
        with pytest.raises(ToolError, match="backwards"):
            _ = await lister.list_mail(
                client,
                received_after=date(2026, 3, 31),
                received_before=date(2026, 3, 1),
                limit=25,
            )

        assert inbox.call_count == 0

    async def test_the_backwards_refusal_names_both_arguments_and_which_takes_the_earlier_date(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refusal:
            _ = await lister.list_mail(
                client,
                received_after=date(2026, 3, 31),
                received_before=date(2026, 3, 1),
                limit=25,
            )

        message = str(refusal.value)
        assert "`received_after`" in message
        assert "`received_before`" in message
        assert "earlier date in `received_after`" in message

    @pytest.mark.parametrize(
        "from_address",
        [
            "Bob Vance",
            "Bob Vance <bob@vance.invalid>",
            "bob@vance.invalid, dana@contoso.invalid",
            "bob",
            "@vance.invalid",
        ],
    )
    async def test_a_sender_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, inbox: respx.Route, from_address: str
    ) -> None:
        """`eq` on a display name matches nothing, and Graph answers that with an empty page, not
        an error. So it reads as "no mail from Bob" to a caller who spelled Bob's name."""
        with pytest.raises(ToolError, match="one address"):
            _ = await lister.list_mail(client, from_address=from_address, limit=25)

        assert inbox.call_count == 0

    @pytest.mark.usefixtures("inbox", "inbox_messages")
    async def test_a_sender_is_taken_with_surrounding_space_trimmed(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        _ = await lister.list_mail(
            client,
            received_after=date(2026, 3, 4),
            from_address="  bob@vance.invalid  ",
            limit=25,
        )

        assert inbox_messages.calls.last.request.url.params["$filter"].endswith(
            "and from/emailAddress/address eq 'bob@vance.invalid'"
        )

    @pytest.mark.usefixtures("inbox", "inbox_messages")
    async def test_a_window_of_one_day_is_not_backwards(self, client: GraphServiceClient) -> None:
        """The whole of that day is inside both bounds, so the narrowest window there is remains a
        window rather than a refusal."""
        answered = await lister.list_mail(
            client, received_after=date(2026, 3, 4), received_before=date(2026, 3, 4), limit=25
        )

        assert answered.messages != []


class TestTheSchemaItPublishes:
    async def test_the_two_ways_in_are_published_as_alternatives(
        self, transport: httpx.AsyncClient
    ) -> None:
        """FastMCP validates arguments against the signature. So the schema must also state the
        constraint that the runtime refusal enforces, or no client can see it."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters["not"] == {"required": ["folder", "folder_ref"]}

    async def test_neither_way_in_is_required_on_its_own(
        self, transport: httpx.AsyncClient
    ) -> None:
        """The default call names no folder at all and lists the Inbox."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("required", []) == []
        assert tool.parameters["properties"]["folder"]["default"] == "inbox"


class TestMailboxTargeting:
    async def test_no_mailbox_lists_the_signed_in_users_own_mailbox(
        self, client: GraphServiceClient, inbox: respx.Route, inbox_messages: respx.Route
    ) -> None:
        _ = await lister.list_mail(client, limit=25)

        assert inbox.called
        assert inbox_messages.called

    async def test_a_mailbox_lists_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        folder = graph.get("/users/alex@example.invalid/mailFolders/inbox").mock(
            return_value=httpx.Response(200, json=_folder_payload())
        )
        messages = graph.get("/users/alex@example.invalid/mailFolders/inbox/messages").mock(
            return_value=_page(_message_payload(_FIRST_ID))
        )

        listed = await lister.list_mail(client, limit=25, mailbox="alex@example.invalid")

        assert folder.called
        assert messages.called
        assert listed.messages[0].uri == MailMessageHandle(_FIRST_ID).uri


class TestGraphFailures:
    async def test_a_refused_folder_read_stops_before_the_messages_are_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter, inbox_messages: respx.Route
    ) -> None:
        graph.get(_INBOX).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_mail(client, limit=25)

        assert inbox_messages.call_count == 0

    @pytest.mark.usefixtures("inbox")
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        inbox_messages.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_mail(client, limit=25)

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        """`Mail.Read.Shared` is the permission that Microsoft's shared-folder walkthrough names
        to list messages in a mailbox other than `/me`."""
        assert lister.GRAPH_PERMISSIONS == ("Mail.Read", "Mail.Read.Shared")

    def test_a_folder_that_will_not_resolve_is_answered_with_both_recoveries(self) -> None:
        """A 404 here is not the usual "make sure that you copied the id" advice. One way in is
        a handle that this connector minted. The other is a name that no id was ever copied
        from."""
        assert "outlook_browse_folders" in lister.GRAPH_NOT_FOUND
