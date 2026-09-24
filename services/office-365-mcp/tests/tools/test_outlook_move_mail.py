import json
from collections.abc import Mapping
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import (
    GraphForbidden,
    GraphNotFound,
    GraphSettings,
    GraphUnavailable,
)
from office_365_mcp.shared.handles import MailFolderHandle, MailMessageHandle
from office_365_mcp.tools import outlook_move_mail as mover

_FIRST_ID = "AAMkAGI2SYNTHETIC-immutable-0001="
_SECOND_ID = "AAMkAGI2SYNTHETIC-immutable-0002="
_THIRD_ID = "AAMkAGI2SYNTHETIC-immutable-0003="

_FIRST_MOVED_ID = "AAMkAGI2SYNTHETIC-immutable-0001-moved="
_SECOND_MOVED_ID = "AAMkAGI2SYNTHETIC-immutable-0002-moved="

_ARCHIVE_ID = "AQMkADAwSYNTHETIC-archive"
_ARCHIVE = f"/me/mailFolders/{_ARCHIVE_ID}"
_ARCHIVE_REF = MailFolderHandle(_ARCHIVE_ID).uri

_WELL_KNOWN = "/me/mailFolders/archive"

_NEVER_A_DESTINATION: tuple[str, ...] = (
    "recoverableitemsdeletions",
    "msgfolderroot",
    "searchfolders",
    "outbox",
    "scheduled",
    "conflicts",
    "localfailures",
    "serverfailures",
    "syncissues",
)


def _move_path(message_id: str) -> str:
    return f"/me/messages/{quote(message_id, safe='')}/move"


def _moved(new_id: str) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "id": new_id,
            "subject": "Invoice 4471",
            "parentFolderId": _ARCHIVE_ID,
        },
    )


def _refused(status: int) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": "ErrorItemNotFound", "message": "not found"}}
    )


def _folder_payload(
    *,
    display_name: str | None = "Archive",
    is_hidden: bool | None = False,
    odata_type: str | None = None,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"displayName": display_name, "isHidden": is_hidden}
    if odata_type is not None:
        payload["@odata.type"] = odata_type
    payload.update(extra or {})
    return payload


_SEARCH_FOLDER_PROPERTIES: Mapping[str, object] = {
    "filterQuery": "flagStatus eq 'flagged'",
    "sourceFolderIds": ["AQMkADAwSYNTHETIC-inbox"],
    "includeNestedFolders": True,
    "isSupported": True,
}


def _sent_body(route: respx.Route) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(route.calls.last.request.content))


@pytest.fixture
def archive(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_ARCHIVE).mock(return_value=httpx.Response(200, json=_folder_payload()))


@pytest.fixture
def first_move(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_move_path(_FIRST_ID)).mock(return_value=_moved(_FIRST_MOVED_ID))


@pytest.fixture
def second_move(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_move_path(_SECOND_ID)).mock(return_value=_moved(_SECOND_MOVED_ID))


class TestTheRequestsItMakes:
    @pytest.mark.usefixtures("first_move")
    async def test_a_well_known_name_is_the_destination_and_no_folder_is_read(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_move: respx.Route
    ) -> None:
        named = graph.get(_WELL_KNOWN)

        _ = await mover.move_mail(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
        )

        assert _sent_body(first_move)["DestinationId"] == "archive"
        assert named.call_count == 0, "a well-known name needs no folder read"

    @pytest.mark.usefixtures("archive")
    async def test_a_folder_handle_sends_that_folders_own_id(
        self, client: GraphServiceClient, first_move: respx.Route
    ) -> None:
        _ = await mover.move_mail(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert _sent_body(first_move)["DestinationId"] == _ARCHIVE_ID

    async def test_each_message_is_moved_by_a_request_of_its_own(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        first_move: respx.Route,
        second_move: respx.Route,
    ) -> None:
        third = graph.post(_move_path(_THIRD_ID)).mock(return_value=_moved("NEW-0003="))

        _ = await mover.move_mail(
            client,
            message_refs=[
                MailMessageHandle(_FIRST_ID).uri,
                MailMessageHandle(_SECOND_ID).uri,
                MailMessageHandle(_THIRD_ID).uri,
            ],
            destination="deleteditems",
        )

        assert (first_move.call_count, second_move.call_count, third.call_count) == (1, 1, 1)

    async def test_every_move_declares_the_immutable_id_space(
        self, client: GraphServiceClient, first_move: respx.Route, second_move: respx.Route
    ) -> None:
        _ = await mover.move_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        for route in (first_move, second_move):
            assert 'IdType="ImmutableId"' in route.calls.last.request.headers["Prefer"]

    @pytest.mark.usefixtures("first_move")
    async def test_the_preference_does_not_leak_onto_the_folder_read(
        self, client: GraphServiceClient, archive: respx.Route
    ) -> None:
        _ = await mover.move_mail(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert archive.call_count == 1
        assert "Prefer" not in archive.calls.last.request.headers


class TestAMoveIsNeverRetried:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_move_that_answers_503_is_sent_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        assert GraphSettings().max_retries > 0, "the transport retries nothing, so this proves none"
        route = graph.post(_move_path(_FIRST_ID)).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await mover.move_mail(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
            )

        assert route.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_one_message_failing_that_way_does_not_retry_the_others_either(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_move: respx.Route
    ) -> None:
        second = graph.post(_move_path(_SECOND_ID)).mock(return_value=httpx.Response(503))

        answer = await mover.move_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        assert (first_move.call_count, second.call_count) == (1, 1)
        assert answer.failed_count == 1


class TestTheHandlesItHandsBack:
    @pytest.mark.usefixtures("first_move")
    async def test_the_new_handle_is_read_off_graphs_answer(
        self, client: GraphServiceClient
    ) -> None:
        answer = await mover.move_mail(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
        )

        assert answer.messages[0].new_uri == MailMessageHandle(_FIRST_MOVED_ID).uri

    @pytest.mark.usefixtures("first_move")
    async def test_the_new_handle_is_not_the_one_that_was_passed_in(
        self, client: GraphServiceClient
    ) -> None:
        answer = await mover.move_mail(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
        )

        row = answer.messages[0]
        assert row.uri == MailMessageHandle(_FIRST_ID).uri
        assert row.new_uri != row.uri

    @pytest.mark.usefixtures("first_move", "second_move")
    async def test_every_row_names_the_handle_it_came_in_with(
        self, client: GraphServiceClient
    ) -> None:
        answer = await mover.move_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        assert [row.uri for row in answer.messages] == [
            MailMessageHandle(_FIRST_ID).uri,
            MailMessageHandle(_SECOND_ID).uri,
        ]
        assert [row.new_uri for row in answer.messages] == [
            MailMessageHandle(_FIRST_MOVED_ID).uri,
            MailMessageHandle(_SECOND_MOVED_ID).uri,
        ]

    async def test_a_message_that_did_not_move_answers_no_new_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_move: respx.Route
    ) -> None:
        _ = first_move
        _ = graph.post(_move_path(_SECOND_ID)).mock(return_value=_refused(404))

        answer = await mover.move_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        failed = answer.messages[1]
        assert failed.moved is False
        assert failed.new_uri is None
        assert failed.uri == MailMessageHandle(_SECOND_ID).uri

    def test_the_replacement_handle_says_the_old_one_is_dead(self) -> None:
        described = mover.MovedMessage.model_fields["new_uri"].description

        assert described is not None
        assert "the only valid handle from now on" in described
        assert "is now dead" in described
        assert (
            "every earlier handle for it, from a search, a listing, or a thread read" in described
        )


class TestWhenPartOfTheBatchFails:
    async def test_a_failure_after_a_move_is_reported_rather_than_raised(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_move: respx.Route
    ) -> None:
        _ = first_move
        _ = graph.post(_move_path(_SECOND_ID)).mock(return_value=_refused(404))

        answer = await mover.move_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        assert [row.moved for row in answer.messages] == [True, False]
        assert answer.messages[1].error is not None

    async def test_a_failure_before_a_move_is_reported_the_same_way(
        self, client: GraphServiceClient, graph: respx.MockRouter, second_move: respx.Route
    ) -> None:
        _ = second_move
        _ = graph.post(_move_path(_FIRST_ID)).mock(return_value=_refused(404))

        answer = await mover.move_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        assert [row.moved for row in answer.messages] == [False, True]

    @pytest.mark.usefixtures("first_move")
    async def test_the_counts_split_the_batch_between_them(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_move_path(_SECOND_ID)).mock(return_value=_refused(404))
        _ = graph.post(_move_path(_THIRD_ID)).mock(return_value=_refused(404))

        answer = await mover.move_mail(
            client,
            message_refs=[
                MailMessageHandle(_FIRST_ID).uri,
                MailMessageHandle(_SECOND_ID).uri,
                MailMessageHandle(_THIRD_ID).uri,
            ],
            destination="archive",
        )

        assert (answer.moved_count, answer.failed_count) == (1, 2)
        assert answer.moved_count + answer.failed_count == len(answer.messages)

    async def test_a_batch_where_nothing_moved_raises_instead_of_answering(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_move_path(_FIRST_ID)).mock(return_value=_refused(404))
        _ = graph.post(_move_path(_SECOND_ID)).mock(return_value=_refused(404))

        with pytest.raises(GraphNotFound):
            _ = await mover.move_mail(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
                destination="archive",
            )

    async def test_a_refused_permission_reaches_the_caller_as_a_refusal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_move_path(_FIRST_ID)).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await mover.move_mail(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
            )


class TestTheDestinationItRefuses:
    @pytest.mark.usefixtures("first_move")
    async def test_a_hidden_folder_is_refused_and_nothing_moves(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_move: respx.Route
    ) -> None:
        _ = graph.get(_ARCHIVE).mock(
            return_value=httpx.Response(200, json=_folder_payload(is_hidden=True))
        )

        with pytest.raises(ToolError, match="hidden"):
            _ = await mover.move_mail(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
            )

        assert first_move.call_count == 0

    @pytest.mark.usefixtures("first_move")
    async def test_a_search_folder_is_refused_and_nothing_moves(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_move: respx.Route
    ) -> None:
        _ = graph.get(_ARCHIVE).mock(
            return_value=httpx.Response(
                200,
                json=_folder_payload(
                    display_name="Unread mail",
                    odata_type="#microsoft.graph.mailSearchFolder",
                ),
            )
        )

        with pytest.raises(ToolError, match="search folder"):
            _ = await mover.move_mail(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
            )

        assert first_move.call_count == 0

    @pytest.mark.usefixtures("first_move")
    async def test_a_search_folder_is_refused_even_with_no_odata_type(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_move: respx.Route
    ) -> None:
        _ = graph.get(_ARCHIVE).mock(
            return_value=httpx.Response(
                200,
                json=_folder_payload(display_name="Unread mail", extra=_SEARCH_FOLDER_PROPERTIES),
            )
        )

        with pytest.raises(ToolError, match="search folder"):
            _ = await mover.move_mail(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
            )

        assert first_move.call_count == 0

    @pytest.mark.usefixtures("first_move")
    async def test_the_destination_read_narrows_nothing(
        self, client: GraphServiceClient, archive: respx.Route
    ) -> None:
        _ = await mover.move_mail(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert "select" not in str(archive.calls.last.request.url).casefold()

    @pytest.mark.usefixtures("first_move")
    async def test_the_folder_is_read_again_on_every_call(
        self, client: GraphServiceClient, archive: respx.Route
    ) -> None:
        refs = [MailMessageHandle(_FIRST_ID).uri]

        _ = await mover.move_mail(client, message_refs=refs, folder_ref=_ARCHIVE_REF)
        _ = await mover.move_mail(client, message_refs=refs, folder_ref=_ARCHIVE_REF)

        assert archive.call_count == 2

    @pytest.mark.usefixtures("archive")
    async def test_a_folder_graph_named_is_reported_by_its_name(
        self, client: GraphServiceClient, first_move: respx.Route
    ) -> None:
        _ = first_move
        answer = await mover.move_mail(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert answer.destination == "Archive"


class TestWhatItRefusesBeforeReachingGraph:
    async def test_both_destinations_together_move_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = graph.post(_move_path(_FIRST_ID))

        with pytest.raises(ToolError, match="alternatives"):
            _ = await mover.move_mail(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri],
                destination="archive",
                folder_ref=_ARCHIVE_REF,
            )

        assert move.call_count == 0

    async def test_no_destination_at_all_moves_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = graph.post(_move_path(_FIRST_ID))

        with pytest.raises(ToolError, match="no destination"):
            _ = await mover.move_mail(client, message_refs=[MailMessageHandle(_FIRST_ID).uri])

        assert move.call_count == 0

    @pytest.mark.parametrize(
        "folder_ref",
        [
            "Archive",
            "archive",
            _ARCHIVE_ID,
            "outlook:///folders/",
            MailMessageHandle(_FIRST_ID).uri,
        ],
    )
    async def test_a_folder_ref_that_is_not_a_folder_handle_moves_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, folder_ref: str
    ) -> None:
        move = graph.post(_move_path(_FIRST_ID))

        with pytest.raises(ToolError, match="folder handle"):
            _ = await mover.move_mail(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=folder_ref
            )

        assert move.call_count == 0

    @pytest.mark.parametrize(
        "message_ref",
        [
            "Invoice 4471",
            "bob@vance.invalid",
            _FIRST_ID,
            "outlook:///messages/",
            MailFolderHandle(_ARCHIVE_ID).uri,
        ],
    )
    async def test_a_message_ref_that_is_not_a_message_handle_moves_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, message_ref: str
    ) -> None:
        move = graph.post(_move_path(_FIRST_ID))

        with pytest.raises(ToolError, match="message handles"):
            _ = await mover.move_mail(client, message_refs=[message_ref], destination="archive")

        assert move.call_count == 0

    async def test_one_bad_handle_stops_the_whole_batch_before_any_of_it_moves(
        self, client: GraphServiceClient, first_move: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="message handles"):
            _ = await mover.move_mail(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri, "not-a-handle"],
                destination="archive",
            )

        assert first_move.call_count == 0

    @pytest.mark.parametrize("size", [0, mover.MAX_MESSAGES + 1])
    async def test_a_batch_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, size: int
    ) -> None:
        refs = [MailMessageHandle(f"{_FIRST_ID}{index}").uri for index in range(size)]

        with pytest.raises(AssertionError):
            _ = await mover.move_mail(client, message_refs=refs, destination="archive")


class TestTheSchemaItPublishes:
    async def _tool_schema(self, transport: httpx.AsyncClient) -> Mapping[str, object]:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        mover.register(mcp, transport)
        tool = await mcp.get_tool(mover.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        return tool.parameters

    async def test_the_bulk_cap_is_published_on_the_batch_itself(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters = await self._tool_schema(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])

        assert properties["message_refs"]["minItems"] == 1
        assert properties["message_refs"]["maxItems"] == mover.MAX_MESSAGES
        assert mover.MAX_MESSAGES == 20

    async def test_only_the_batch_is_required_of_a_client(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters = await self._tool_schema(transport)

        assert parameters["required"] == ["message_refs"]

    async def test_the_destination_vocabulary_is_the_closed_one(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters = await self._tool_schema(transport)
        defined = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])

        assert defined["WellKnownFolder"]["enum"] == [
            "inbox",
            "sentitems",
            "drafts",
            "archive",
            "deleteditems",
            "junkemail",
            "clutter",
        ]

    async def test_the_folders_microsoft_publishes_and_this_excludes_stay_excluded(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters = await self._tool_schema(transport)
        defined = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        offered = cast("list[str]", defined["WellKnownFolder"]["enum"])

        assert [name for name in _NEVER_A_DESTINATION if name in offered] == []

    async def test_it_declares_itself_a_write_that_can_destroy(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        mover.register(mcp, transport)

        tool = await mcp.get_tool(mover.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is True
        assert tool.annotations.idempotent_hint is False


class TestMailboxTargeting:
    async def test_no_mailbox_moves_mail_in_the_signed_in_users_own_mailbox(
        self, client: GraphServiceClient, archive: respx.Route, first_move: respx.Route
    ) -> None:
        _ = await mover.move_mail(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert archive.called
        assert first_move.called

    async def test_a_mailbox_moves_mail_in_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        folder = graph.get(f"/users/alex@example.invalid/mailFolders/{_ARCHIVE_ID}").mock(
            return_value=httpx.Response(200, json=_folder_payload())
        )
        move = graph.post(
            f"/users/alex@example.invalid/messages/{quote(_FIRST_ID, safe='')}/move"
        ).mock(return_value=_moved(_FIRST_MOVED_ID))

        moved = await mover.move_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri],
            folder_ref=_ARCHIVE_REF,
            mailbox="alex@example.invalid",
        )

        assert folder.called
        assert move.called
        assert moved.messages[0].moved is True


class TestWhatItSaysAboutItself:
    def test_the_permission_is_the_write_one_microsoft_documents(self) -> None:
        assert mover.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

    def test_the_description_teaches_that_this_is_how_a_message_is_deleted(self) -> None:
        described = mover._DESCRIPTION  # pyright: ignore[reportPrivateUsage]

        assert "deleteditems" in described
        assert "the only way this connector erases mail" in described
        assert "stays recoverable in Deleted Items" in described
        assert "no permanent-erase operation" in described

    def test_the_description_warns_that_the_handles_passed_in_die(self) -> None:
        uri_described = mover.MovedMessage.model_fields["uri"].description
        new_uri_described = mover.MovedMessage.model_fields["new_uri"].description

        assert uri_described is not None
        assert "it addresses nothing" in uri_described
        assert "never pass it to another tool" in uri_described

        assert new_uri_described is not None
        assert "is now dead" in new_uri_described

    def test_a_stale_handle_is_answered_with_both_recoveries(self) -> None:
        assert "outlook_browse_folders" in mover.GRAPH_NOT_FOUND
        assert "outlook_search_mail" in mover.GRAPH_NOT_FOUND

    def test_the_example_call_reaches_graph_without_a_folder_read(self) -> None:
        assert mover.GRAPH_CALL_EXAMPLE["destination"] == "archive"
        refs = cast("list[str]", mover.GRAPH_CALL_EXAMPLE["message_refs"])
        assert all(ref.startswith("outlook:///messages/") for ref in refs)
        assert 1 <= len(refs) <= mover.MAX_MESSAGES
