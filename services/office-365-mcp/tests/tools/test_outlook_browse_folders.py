"""`outlook_browse_folders`: the level it asks Graph for, the level it answers, what it refuses.

Every response body here is synthesised. None came from a real mailbox.
"""

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.handles import MailFolderHandle, MailMessageHandle
from office_365_mcp.tools import outlook_browse_folders as browser

from .conftest import GRAPH_V1

_TOP_LEVEL = "/me/mailFolders"

_INBOX_ID = "AQMkADAwSYNTHETIC-inbox"
_ARCHIVE_ID = "AQMkADAwSYNTHETIC-archive"
_PROJECTS_ID = "AQMkADAwSYNTHETIC-projects"
_RECOVERABLE_ID = "AQMkADAwSYNTHETIC-recoverable"

_INBOX_CHILDREN = f"{_TOP_LEVEL}/{_INBOX_ID}/childFolders"


def _folder_payload(
    folder_id: str,
    *,
    display_name: str | None = "Inbox",
    total_items: int | None = 412,
    unread_items: int | None = 17,
    child_folder_count: int | None = 2,
    is_hidden: bool = False,
) -> dict[str, object]:
    return {
        "id": folder_id,
        "displayName": display_name,
        "totalItemCount": total_items,
        "unreadItemCount": unread_items,
        "childFolderCount": child_folder_count,
        "isHidden": is_hidden,
    }


def _page(*folders: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(folders)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


@pytest.fixture
def top_level(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_TOP_LEVEL)


@pytest.fixture
def inbox_children(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_INBOX_CHILDREN)


class TestTheLevelItAsksFor:
    async def test_no_parent_asks_for_the_top_of_the_mailbox(
        self, client: GraphServiceClient, top_level: respx.Route, inbox_children: respx.Route
    ) -> None:
        top_level.mock(return_value=_page(_folder_payload(_INBOX_ID)))

        _ = await browser.browse_folders(client, limit=25)

        assert top_level.call_count == 1
        assert inbox_children.call_count == 0

    async def test_a_folder_handle_asks_for_that_folders_children(
        self, client: GraphServiceClient, top_level: respx.Route, inbox_children: respx.Route
    ) -> None:
        inbox_children.mock(return_value=_page(_folder_payload(_PROJECTS_ID)))

        _ = await browser.browse_folders(client, parent=MailFolderHandle(_INBOX_ID).uri, limit=25)

        assert inbox_children.call_count == 1
        assert top_level.call_count == 0, "a parent addresses one folder, not the mailbox root"

    async def test_it_asks_for_the_counts_graph_gives_away_on_the_folder(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        """Microsoft recommends these two over counting a folder's messages with `$count` and
        `$filter`, which it warns can incur significant latency."""
        top_level.mock(return_value=_page(_folder_payload(_INBOX_ID)))

        _ = await browser.browse_folders(client, limit=25)

        params = top_level.calls.last.request.url.params
        assert params["$select"].split(",") == [
            "id",
            "displayName",
            "totalItemCount",
            "unreadItemCount",
            "childFolderCount",
            "isHidden",
        ]
        assert "$count" not in params
        assert "$filter" not in params

    async def test_it_never_expands_a_second_level_out_of_one_request(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        """`$expand=childFolders` reaches one level further and stops again, which would move this
        tool's boundary without removing it and make `child_folder_count` mean two things."""
        top_level.mock(return_value=_page(_folder_payload(_INBOX_ID)))

        _ = await browser.browse_folders(client, limit=25)

        assert "$expand" not in top_level.calls.last.request.url.params

    async def test_hidden_folders_are_left_out_unless_they_are_asked_for(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        top_level.mock(return_value=_page(_folder_payload(_INBOX_ID)))

        _ = await browser.browse_folders(client, limit=25)

        assert "includeHiddenFolders" not in top_level.calls.last.request.url.params

    async def test_asking_for_hidden_folders_sends_graphs_own_spelling_of_true(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        """The SDK types this query parameter as a string, so a bool would reach Graph as `True`."""
        top_level.mock(return_value=_page(_folder_payload(_INBOX_ID)))

        _ = await browser.browse_folders(client, include_hidden=True, limit=25)

        assert top_level.calls.last.request.url.params["includeHiddenFolders"] == "true"

    async def test_the_hidden_option_travels_to_a_childrens_request_too(
        self, client: GraphServiceClient, inbox_children: respx.Route
    ) -> None:
        inbox_children.mock(return_value=_page(_folder_payload(_PROJECTS_ID)))

        _ = await browser.browse_folders(
            client, parent=MailFolderHandle(_INBOX_ID).uri, include_hidden=True, limit=25
        )

        assert inbox_children.calls.last.request.url.params["includeHiddenFolders"] == "true"

    async def test_the_window_is_asked_of_graph_rather_than_only_applied_here(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        top_level.mock(return_value=_page(_folder_payload(_INBOX_ID)))

        _ = await browser.browse_folders(client, limit=7)

        assert top_level.calls.last.request.url.params["$top"] == "7"

    @pytest.mark.parametrize("limit", [0, browser.MAX_FOLDERS + 1])
    async def test_a_limit_outside_the_window_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await browser.browse_folders(client, limit=limit)


class TestTheLevelItAnswers:
    async def test_each_folder_carries_the_handle_that_browses_it(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        top_level.mock(
            return_value=_page(
                _folder_payload(_INBOX_ID), _folder_payload(_ARCHIVE_ID, display_name="Archive")
            )
        )

        level = await browser.browse_folders(client, limit=25)

        assert [folder.uri for folder in level.folders] == [
            MailFolderHandle(_INBOX_ID).uri,
            MailFolderHandle(_ARCHIVE_ID).uri,
        ]

    async def test_a_handle_it_minted_browses_the_level_below_that_folder(
        self, client: GraphServiceClient, top_level: respx.Route, inbox_children: respx.Route
    ) -> None:
        """The round trip the answer promises: the `uri` of a folder with children, handed straight
        back as `parent`, addresses that folder's children and nothing else."""
        top_level.mock(return_value=_page(_folder_payload(_INBOX_ID, child_folder_count=1)))
        inbox_children.mock(
            return_value=_page(_folder_payload(_PROJECTS_ID, display_name="Projects"))
        )

        inbox = (await browser.browse_folders(client, limit=25)).folders[0]
        below = await browser.browse_folders(client, parent=inbox.uri, limit=25)

        assert [folder.display_name for folder in below.folders] == ["Projects"]

    async def test_it_reports_the_counts_and_whether_there_is_more_underneath(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        top_level.mock(
            return_value=_page(
                _folder_payload(
                    _INBOX_ID,
                    display_name="Inbox",
                    total_items=412,
                    unread_items=17,
                    child_folder_count=2,
                )
            )
        )

        folder = (await browser.browse_folders(client, limit=25)).folders[0]

        assert folder.display_name == "Inbox"
        assert folder.total_items == 412
        assert folder.unread_items == 17
        assert folder.child_folder_count == 2
        assert folder.is_hidden is False

    async def test_a_folder_graph_reported_no_counts_for_is_still_listed(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        """A count is a number or nothing, never a zero this tool invented: "no folders below" and
        "Graph did not say" are different answers to `child_folder_count`."""
        top_level.mock(
            return_value=_page(
                _folder_payload(
                    _INBOX_ID,
                    display_name=None,
                    total_items=None,
                    unread_items=None,
                    child_folder_count=None,
                )
            )
        )

        folder = (await browser.browse_folders(client, limit=25)).folders[0]

        assert folder.uri == MailFolderHandle(_INBOX_ID).uri
        assert folder.display_name is None
        assert folder.total_items is None
        assert folder.unread_items is None
        assert folder.child_folder_count is None

    async def test_a_hidden_folder_is_reported_as_hidden(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        """A folder Outlook does not show the user still holds mail, so the flag is reported rather
        than filtered on."""
        top_level.mock(
            return_value=_page(
                _folder_payload(_INBOX_ID),
                _folder_payload(
                    _RECOVERABLE_ID,
                    display_name="Recoverable Items",
                    child_folder_count=0,
                    is_hidden=True,
                ),
            )
        )

        level = await browser.browse_folders(client, include_hidden=True, limit=25)

        assert [folder.is_hidden for folder in level.folders] == [False, True]

    async def test_the_pages_of_one_level_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph chooses its own page size for this collection, so a level wider than it arrives in
        pieces and reading only the first one would silently drop folders.

        The cursor routes are registered before the bare one, which respx matches in registration
        order: the bare path matches a `$skiptoken` request too, and would answer every page.
        """
        graph.get(_TOP_LEVEL, params={"$skiptoken": "second"}).mock(
            return_value=_page(_folder_payload(_ARCHIVE_ID, display_name="Archive"))
        )
        graph.get(_TOP_LEVEL).mock(
            return_value=_page(
                _folder_payload(_INBOX_ID),
                next_link=f"{GRAPH_V1}{_TOP_LEVEL}?$skiptoken=second",
            )
        )

        level = await browser.browse_folders(client, limit=25)

        assert [folder.display_name for folder in level.folders] == ["Inbox", "Archive"]
        assert level.capped is False, "the walk reached the end of this level"

    async def test_an_empty_page_in_the_middle_does_not_end_the_level(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph sends the odd empty page with an `@odata.nextLink` still set, and the SDK's own
        page walker reads one as the end of the collection."""
        graph.get(_TOP_LEVEL, params={"$skiptoken": "third"}).mock(
            return_value=_page(_folder_payload(_ARCHIVE_ID, display_name="Archive"))
        )
        graph.get(_TOP_LEVEL, params={"$skiptoken": "second"}).mock(
            return_value=_page(next_link=f"{GRAPH_V1}{_TOP_LEVEL}?$skiptoken=third")
        )
        graph.get(_TOP_LEVEL).mock(
            return_value=_page(
                _folder_payload(_INBOX_ID),
                next_link=f"{GRAPH_V1}{_TOP_LEVEL}?$skiptoken=second",
            )
        )

        level = await browser.browse_folders(client, limit=25)

        assert [folder.display_name for folder in level.folders] == ["Inbox", "Archive"]

    async def test_a_cap_that_left_more_of_the_level_on_offer_says_capped(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        top_level.mock(
            return_value=_page(
                _folder_payload(_INBOX_ID), _folder_payload(_ARCHIVE_ID, display_name="Archive")
            )
        )

        level = await browser.browse_folders(client, limit=1)

        assert [folder.display_name for folder in level.folders] == ["Inbox"]
        assert level.capped is True

    async def test_a_window_filled_exactly_by_the_end_of_the_level_is_not_capped(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        """`capped` means a cap stopped the walk with more still on offer, never that the answer
        was short: a level that ran out on its own says False however tight the window was."""
        top_level.mock(
            return_value=_page(
                _folder_payload(_INBOX_ID), _folder_payload(_ARCHIVE_ID, display_name="Archive")
            )
        )

        level = await browser.browse_folders(client, limit=2)

        assert len(level.folders) == 2
        assert level.capped is False

    async def test_a_folder_with_no_children_answers_an_empty_level(
        self, client: GraphServiceClient, inbox_children: respx.Route
    ) -> None:
        inbox_children.mock(return_value=_page())

        level = await browser.browse_folders(
            client, parent=MailFolderHandle(_INBOX_ID).uri, limit=25
        )

        assert level.folders == []
        assert level.capped is False, "an empty level is the whole of it, not a cap"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "parent",
        [
            "Inbox",
            "inbox",
            _INBOX_ID,
            "outlook:///folders/",
            MailMessageHandle("AAMkAGI2SYNTHETIC-message").uri,
        ],
    )
    async def test_a_parent_that_is_not_a_folder_handle_never_reaches_graph(
        self, client: GraphServiceClient, top_level: respx.Route, parent: str
    ) -> None:
        """A name, a well-known name, a bare id and another family's handle are all not one, and
        Graph would answer several of them with a listing of the wrong thing."""
        with pytest.raises(ToolError, match="folder handle"):
            _ = await browser.browse_folders(client, parent=parent, limit=25)

        assert top_level.call_count == 0

    async def test_the_refusal_says_how_to_reach_the_top_of_the_mailbox(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="Omit `parent`"):
            _ = await browser.browse_folders(client, parent="Inbox", limit=25)


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, top_level: respx.Route
    ) -> None:
        top_level.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await browser.browse_folders(client, limit=25)

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert browser.GRAPH_PERMISSIONS == ("Mail.Read",)

    def test_a_stale_folder_handle_is_answered_with_the_recovery_that_works(self) -> None:
        """A 404 here is not the default "check you copied the id" advice: the id was this
        connector's own, and Microsoft's pages disagree about whether a folder id outlives a move.
        """
        assert "outlook_browse_folders" in browser.GRAPH_NOT_FOUND
