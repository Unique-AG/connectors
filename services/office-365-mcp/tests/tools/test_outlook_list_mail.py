"""`outlook_list_mail`: the query it composes, the folder it answers, what it refuses.

The query is most of this file. Microsoft answers `InefficientFilter` to an `$orderby` naming a
property `$filter` does not, in a different order, or after an unfiltered one, so the assertions
below pin the one construction that cannot break those rules: `receivedDateTime` ordered always,
`receivedDateTime` filtered when a date was given, and nothing else in either — `isRead` least of
all, which is why `unread_only` is applied to the rows rather than to the query.

Every response body here is synthesised. None came from a real mailbox.
"""

from datetime import date

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
) -> dict[str, object]:
    return {
        "id": message_id,
        "subject": subject,
        "bodyPreview": "Please find the invoice attached.",
        "from": {"emailAddress": {"name": "Bob Vance", "address": "bob@vance.invalid"}},
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
        """Microsoft recommends these over counting a folder's messages with `$count` and
        `$filter`, which it warns can incur significant latency."""
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
    @pytest.mark.parametrize(
        ("unread_only", "received_after"),
        [
            (False, None),
            (True, None),
            (False, date(2026, 3, 4)),
            (True, date(2026, 3, 4)),
        ],
    )
    async def test_receipt_order_is_unconditional(
        self,
        client: GraphServiceClient,
        inbox_messages: respx.Route,
        unread_only: bool,
        received_after: date | None,
    ) -> None:
        """A promise of "newest first" kept only for some arguments is worse than none."""
        _ = await lister.list_mail(
            client, unread_only=unread_only, received_after=received_after, limit=25
        )

        assert inbox_messages.calls.last.request.url.params["$orderby"] == "receivedDateTime desc"

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
        """Microsoft's rule, and the reason this tool has exactly one orderable property: every
        property in `$orderby` must also be in `$filter`, in the same order, and first."""
        _ = await lister.list_mail(client, received_after=date(2026, 3, 4), limit=25)

        params = inbox_messages.calls.last.request.url.params
        assert params["$filter"] == "receivedDateTime ge 2026-03-04T00:00:00Z"
        assert params["$orderby"].split(" ")[0] == params["$filter"].split(" ")[0]

    @pytest.mark.usefixtures("inbox")
    @pytest.mark.parametrize("received_after", [None, date(2026, 3, 4)])
    async def test_the_filter_never_carries_is_read(
        self,
        client: GraphServiceClient,
        inbox_messages: respx.Route,
        received_after: date | None,
    ) -> None:
        """`isRead` in `$filter` is unordered beside an `$orderby` on `receivedDateTime`, which
        Microsoft answers with `InefficientFilter`. Read state is a predicate over the rows here,
        so no combination of arguments can put it in the query."""
        _ = await lister.list_mail(
            client, unread_only=True, received_after=received_after, limit=25
        )

        params = inbox_messages.calls.last.request.url.params
        if received_after is None:
            assert "$filter" not in params, "read state is the only thing left to filter on"
        else:
            assert params["$filter"] == "receivedDateTime ge 2026-03-04T00:00:00Z"
            assert "isRead" not in params["$filter"]

    @pytest.mark.usefixtures("inbox")
    async def test_the_first_page_is_never_reached_by_skipping(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """Graph's own `$skip` in an `@odata.nextLink` counts the items the service enumerated, not
        the ones it handed back, so it is followed whole and never composed here."""
        _ = await lister.list_mail(client, limit=25)

        assert "$skip" not in inbox_messages.calls.last.request.url.params

    @pytest.mark.usefixtures("inbox")
    async def test_the_listing_asks_for_ids_that_outlive_the_message_being_filed(
        self, client: GraphServiceClient, inbox_messages: respx.Route
    ) -> None:
        """The same preference `outlook_read_mail` sends on the way in: without it these handles
        would be `RestId`s, which die the moment an inbox rule files the message."""
        _ = await lister.list_mail(client, limit=25)

        assert 'IdType="ImmutableId"' in inbox_messages.calls.last.request.headers["Prefer"]

    @pytest.mark.usefixtures("inbox")
    async def test_the_preference_is_supplied_again_for_every_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`PageIterator` starts from an empty header collection, so a page fetched without it
        would answer in the other id space and mint handles that 404."""
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
        """Kiota's `RequestConfiguration.headers` default is one collection shared process-wide, so
        a preference added to it would reach the folder read of every later call."""
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
        """The names are locale-independent, so they are sent as Microsoft spells them rather than
        resolved to an id first."""
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
        """The cursor route is registered before the bare one, which respx matches in registration
        order: the bare path matches a `$skiptoken` request too and would answer every page."""
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
        """One call lists one folder, and picking one of the two silently would list a folder
        nobody asked for."""
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


class TestTheSchemaItPublishes:
    async def test_the_two_ways_in_are_published_as_alternatives(
        self, transport: httpx.AsyncClient
    ) -> None:
        """FastMCP validates arguments against the signature, so the constraint the runtime refusal
        enforces has to be said in the schema as well or no client can see it."""
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
        assert lister.GRAPH_PERMISSIONS == ("Mail.Read",)

    def test_a_folder_that_will_not_resolve_is_answered_with_both_recoveries(self) -> None:
        """A 404 here is not the default "check you copied the id" advice: one way in is a handle
        this connector minted, the other is a name no id was ever copied from."""
        assert "outlook_browse_folders" in lister.GRAPH_NOT_FOUND
