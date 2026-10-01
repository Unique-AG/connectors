import json
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import FunctionTool
from fastmcp.tools.base import ToolResult
from mcp.types import (
    CallToolRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphSettings,
    GraphUnavailable,
)
from office_365_mcp.shared.handles import MailFolderHandle, MailMessageHandle
from office_365_mcp.shared.mail import WellKnownFolder
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    Confirmed,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import outlook_copy_mail as copier

_FIRST_ID = "AAMkAGI2SYNTHETIC-immutable-0001="
_SECOND_ID = "AAMkAGI2SYNTHETIC-immutable-0002="
_THIRD_ID = "AAMkAGI2SYNTHETIC-immutable-0003="

_FIRST_COPY_ID = "AAMkAGI2SYNTHETIC-immutable-0001-copy="
_SECOND_COPY_ID = "AAMkAGI2SYNTHETIC-immutable-0002-copy="

_ARCHIVE_ID = "AQMkADAwSYNTHETIC-archive"
_ARCHIVE = f"/me/mailFolders/{_ARCHIVE_ID}"
_ARCHIVE_REF = MailFolderHandle(_ARCHIVE_ID).uri

_WELL_KNOWN = "/me/mailFolders/archive"

_MAILBOX = "alex@example.invalid"

_NOT_COPIED = "No message was copied."

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


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _declines(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOT_COPIED


async def _never_asked(question: str, about: str) -> Confirmed:
    raise AssertionError(f"a person was asked {question!r} about {about!r}")


def _questions() -> tuple[list[tuple[str, str]], Confirm]:
    asked: list[tuple[str, str]] = []

    async def capturing(question: str, about: str) -> Confirmed:
        asked.append((question, about))
        return None

    return asked, capturing


async def _copy(
    client: GraphServiceClient,
    *,
    message_refs: Sequence[str],
    destination: WellKnownFolder | None = None,
    folder_ref: str | None = None,
    mailbox: str | None = None,
    confirm: Confirm = _never_asked,
) -> copier.MailCopied:
    answer = await copier.copy_mail(
        client,
        message_refs=message_refs,
        confirm=confirm,
        destination=destination,
        folder_ref=folder_ref,
        mailbox=mailbox,
    )
    assert not isinstance(answer, InputRequiredResult), (
        "the confirmation asked instead of answering"
    )
    return answer


def _copy_path(message_id: str, *, owner: str = "me") -> str:
    return f"/{owner}/messages/{quote(message_id, safe='')}/copy"


def _copied(new_id: str) -> httpx.Response:
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


def _paths(route: respx.Route) -> list[str]:
    return [call.request.url.path for call in cast("Sequence[Call]", route.calls)]


def _sent_body(route: respx.Route) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(route.calls.last.request.content))


def _posted(graph: respx.MockRouter) -> list[str]:
    calls = cast("Sequence[Call]", graph.calls)
    return [call.request.url.path for call in calls if call.request.method == "POST"]


async def _registered(transport: httpx.AsyncClient) -> FunctionTool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    copier.register(mcp, transport)
    tool = await mcp.get_tool(copier.TOOL_NAME)
    assert isinstance(tool, FunctionTool), "register left the tool off the server"
    return tool


def _properties(tool: FunctionTool) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


@pytest.fixture
def archive(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_ARCHIVE).mock(return_value=httpx.Response(200, json=_folder_payload()))


@pytest.fixture
def first_copy(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_copy_path(_FIRST_ID)).mock(return_value=_copied(_FIRST_COPY_ID))


@pytest.fixture
def second_copy(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_copy_path(_SECOND_ID)).mock(return_value=_copied(_SECOND_COPY_ID))


class TestTheRequestsItMakes:
    @pytest.mark.usefixtures("first_copy")
    async def test_a_well_known_name_is_the_destination_and_no_folder_is_read(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_copy: respx.Route
    ) -> None:
        named = graph.get(_WELL_KNOWN)

        _ = await _copy(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
        )

        assert _sent_body(first_copy)["DestinationId"] == "archive"
        assert named.call_count == 0, "a well-known name needs no folder read"

    @pytest.mark.usefixtures("archive")
    async def test_a_folder_handle_sends_that_folders_own_id(
        self, client: GraphServiceClient, first_copy: respx.Route
    ) -> None:
        _ = await _copy(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert _sent_body(first_copy)["DestinationId"] == _ARCHIVE_ID

    async def test_each_message_is_copied_by_a_request_of_its_own(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        first_copy: respx.Route,
        second_copy: respx.Route,
    ) -> None:
        third = graph.post(_copy_path(_THIRD_ID)).mock(return_value=_copied("NEW-0003="))

        _ = await _copy(
            client,
            message_refs=[
                MailMessageHandle(_FIRST_ID).uri,
                MailMessageHandle(_SECOND_ID).uri,
                MailMessageHandle(_THIRD_ID).uri,
            ],
            destination="archive",
        )

        assert (first_copy.call_count, second_copy.call_count, third.call_count) == (1, 1, 1)

    async def test_every_copy_declares_the_immutable_id_space(
        self, client: GraphServiceClient, first_copy: respx.Route, second_copy: respx.Route
    ) -> None:
        _ = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        for route in (first_copy, second_copy):
            assert 'IdType="ImmutableId"' in route.calls.last.request.headers["Prefer"]

    @pytest.mark.usefixtures("first_copy")
    async def test_the_preference_does_not_leak_onto_the_folder_read(
        self, client: GraphServiceClient, archive: respx.Route
    ) -> None:
        _ = await _copy(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert archive.call_count == 1
        assert "Prefer" not in archive.calls.last.request.headers

    async def test_the_call_example_names_a_well_known_destination_and_a_message_handle(
        self, client: GraphServiceClient, first_copy: respx.Route
    ) -> None:
        example = copier.GRAPH_CALL_EXAMPLE
        refs = cast("list[str]", example["message_refs"])
        assert example["destination"] == "archive"
        assert refs
        assert all(ref.startswith("outlook:///messages/") for ref in refs)

        _ = await _copy(
            client,
            message_refs=refs[:1],
            destination=cast("WellKnownFolder", example["destination"]),
        )

        assert first_copy.call_count == 1


class TestABigBatch:
    @pytest.mark.usefixtures("archive")
    async def test_twenty_one_messages_are_all_copied(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        ids = [f"{_FIRST_ID}{index}" for index in range(21)]
        routes = [
            graph.post(_copy_path(one)).mock(return_value=_copied(f"{one}copy")) for one in ids
        ]

        answer = await _copy(
            client,
            message_refs=[MailMessageHandle(one).uri for one in ids],
            folder_ref=_ARCHIVE_REF,
        )

        assert [route.call_count for route in routes] == [1] * 21
        assert answer.copied_count == 21


class TestACopyIsNeverRetried:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_copy_that_answers_503_is_sent_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        assert GraphSettings().max_retries > 0, "the transport retries nothing, so this proves none"
        route = graph.post(_copy_path(_FIRST_ID)).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _copy(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
            )

        assert route.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    @pytest.mark.parametrize("status", [429, 503, 504])
    async def test_a_copy_that_answers_with_a_retriable_status_is_never_sent_again(
        self, client: GraphServiceClient, graph: respx.MockRouter, status: int
    ) -> None:
        route = graph.post(_copy_path(_FIRST_ID)).mock(return_value=httpx.Response(status))

        with pytest.raises(GraphFailure):
            _ = await _copy(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
            )

        assert route.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_one_message_failing_that_way_does_not_retry_the_others_either(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_copy: respx.Route
    ) -> None:
        second = graph.post(_copy_path(_SECOND_ID)).mock(return_value=httpx.Response(503))

        answer = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        assert (first_copy.call_count, second.call_count) == (1, 1)
        assert answer.failed_count == 1


class TestTheHandlesItHandsBack:
    @pytest.mark.usefixtures("first_copy")
    async def test_the_copys_handle_is_read_off_graphs_answer(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _copy(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
        )

        assert answer.messages[0].new_uri == MailMessageHandle(_FIRST_COPY_ID).uri

    @pytest.mark.usefixtures("first_copy")
    async def test_the_row_keeps_the_handle_that_was_passed_in(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _copy(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
        )

        assert answer.messages[0].uri == MailMessageHandle(_FIRST_ID).uri
        assert answer.messages[0].new_uri != answer.messages[0].uri

    @pytest.mark.usefixtures("first_copy", "second_copy")
    async def test_every_row_names_the_handle_it_came_in_with(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        assert [row.uri for row in answer.messages] == [
            MailMessageHandle(_FIRST_ID).uri,
            MailMessageHandle(_SECOND_ID).uri,
        ]
        assert [row.new_uri for row in answer.messages] == [
            MailMessageHandle(_FIRST_COPY_ID).uri,
            MailMessageHandle(_SECOND_COPY_ID).uri,
        ]

    async def test_a_message_that_was_not_copied_answers_no_new_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_copy: respx.Route
    ) -> None:
        _ = first_copy
        _ = graph.post(_copy_path(_SECOND_ID)).mock(return_value=_refused(404))

        answer = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        failed = answer.messages[1]
        assert failed.copied is False
        assert failed.new_uri is None
        assert failed.uri == MailMessageHandle(_SECOND_ID).uri

    def test_the_handle_passed_in_is_said_to_still_address_the_original(self) -> None:
        described = copier.CopiedMessage.model_fields["uri"].description

        assert described is not None
        assert "The original stays in its folder" in described
        assert "still addresses the original" in described

    def test_the_new_handle_is_said_to_address_the_copy(self) -> None:
        described = copier.CopiedMessage.model_fields["new_uri"].description

        assert described is not None
        assert "This is the handle of the copy" in described
        assert "new message in the destination folder" in described

    def test_a_failed_row_says_a_copy_can_exist_after_a_timeout(self) -> None:
        described = copier.CopiedMessage.model_fields["error"].description

        assert described is not None
        assert "After a timeout or an outage, a copy can exist." in described
        assert "outlook_list_mail does not show it in the destination folder" in described


class TestWhenPartOfTheBatchFails:
    async def test_a_failure_after_a_copy_is_reported_rather_than_raised(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_copy: respx.Route
    ) -> None:
        _ = first_copy
        _ = graph.post(_copy_path(_SECOND_ID)).mock(return_value=_refused(404))

        answer = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        assert [row.copied for row in answer.messages] == [True, False]
        assert answer.messages[1].error is not None

    async def test_a_failure_before_a_copy_is_reported_the_same_way(
        self, client: GraphServiceClient, graph: respx.MockRouter, second_copy: respx.Route
    ) -> None:
        _ = second_copy
        _ = graph.post(_copy_path(_FIRST_ID)).mock(return_value=_refused(404))

        answer = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
        )

        assert [row.copied for row in answer.messages] == [False, True]
        assert answer.messages[0].error is not None
        assert answer.messages[1].error is None

    @pytest.mark.usefixtures("first_copy")
    async def test_the_counts_split_the_batch_between_them(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_copy_path(_SECOND_ID)).mock(return_value=_refused(404))
        _ = graph.post(_copy_path(_THIRD_ID)).mock(return_value=_refused(404))

        answer = await _copy(
            client,
            message_refs=[
                MailMessageHandle(_FIRST_ID).uri,
                MailMessageHandle(_SECOND_ID).uri,
                MailMessageHandle(_THIRD_ID).uri,
            ],
            destination="archive",
        )

        assert (answer.copied_count, answer.failed_count) == (1, 2)
        assert answer.copied_count + answer.failed_count == len(answer.messages)

    async def test_a_batch_where_nothing_was_copied_raises_instead_of_answering(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_copy_path(_FIRST_ID)).mock(return_value=_refused(404))
        _ = graph.post(_copy_path(_SECOND_ID)).mock(return_value=_refused(404))

        with pytest.raises(GraphNotFound):
            _ = await _copy(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
                destination="archive",
            )

    async def test_a_refused_permission_reaches_the_caller_as_a_refusal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_copy_path(_FIRST_ID)).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _copy(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
            )

    async def test_a_copy_that_names_no_id_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_copy_path(_FIRST_ID)).mock(
            return_value=httpx.Response(201, json={"subject": "Invoice 4471"})
        )

        with pytest.raises(AssertionError):
            _ = await _copy(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
            )


class TestTheDestinationItRefuses:
    @pytest.mark.usefixtures("first_copy")
    async def test_a_hidden_folder_is_refused_and_nothing_is_copied(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_copy: respx.Route
    ) -> None:
        _ = graph.get(_ARCHIVE).mock(
            return_value=httpx.Response(200, json=_folder_payload(is_hidden=True))
        )

        with pytest.raises(ToolError, match="hidden"):
            _ = await _copy(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
            )

        assert first_copy.call_count == 0

    @pytest.mark.usefixtures("first_copy")
    async def test_a_search_folder_is_refused_and_nothing_is_copied(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_copy: respx.Route
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
            _ = await _copy(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
            )

        assert first_copy.call_count == 0

    @pytest.mark.usefixtures("first_copy")
    async def test_a_search_folder_is_refused_even_with_no_odata_type(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_copy: respx.Route
    ) -> None:
        _ = graph.get(_ARCHIVE).mock(
            return_value=httpx.Response(
                200,
                json=_folder_payload(display_name="Unread mail", extra=_SEARCH_FOLDER_PROPERTIES),
            )
        )

        with pytest.raises(ToolError, match="search folder"):
            _ = await _copy(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
            )

        assert first_copy.call_count == 0

    @pytest.mark.usefixtures("first_copy")
    async def test_the_destination_read_narrows_nothing(
        self, client: GraphServiceClient, archive: respx.Route
    ) -> None:
        _ = await _copy(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert "select" not in str(archive.calls.last.request.url).casefold()

    @pytest.mark.usefixtures("first_copy")
    async def test_the_folder_is_read_again_on_every_call(
        self, client: GraphServiceClient, archive: respx.Route
    ) -> None:
        refs = [MailMessageHandle(_FIRST_ID).uri]

        _ = await _copy(client, message_refs=refs, folder_ref=_ARCHIVE_REF)
        _ = await _copy(client, message_refs=refs, folder_ref=_ARCHIVE_REF)

        assert archive.call_count == 2

    @pytest.mark.usefixtures("archive")
    async def test_a_folder_graph_named_is_reported_by_its_name(
        self, client: GraphServiceClient, first_copy: respx.Route
    ) -> None:
        _ = first_copy
        answer = await _copy(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert answer.destination == "Archive"

    async def test_a_destination_graph_will_not_return_is_a_not_found_and_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, first_copy: respx.Route
    ) -> None:
        _ = graph.get(_ARCHIVE).mock(return_value=_refused(404))

        with pytest.raises(GraphNotFound):
            _ = await _copy(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
            )

        assert first_copy.call_count == 0


class TestWhatItRefusesBeforeReachingGraph:
    async def test_both_destinations_together_copy_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = graph.post(_copy_path(_FIRST_ID))

        with pytest.raises(ToolError, match="alternatives"):
            _ = await _copy(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri],
                destination="archive",
                folder_ref=_ARCHIVE_REF,
            )

        assert copy.call_count == 0

    async def test_no_destination_at_all_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = graph.post(_copy_path(_FIRST_ID))

        with pytest.raises(ToolError, match="no destination"):
            _ = await _copy(client, message_refs=[MailMessageHandle(_FIRST_ID).uri])

        assert copy.call_count == 0

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
    async def test_a_folder_ref_that_is_not_a_folder_handle_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, folder_ref: str
    ) -> None:
        copy = graph.post(_copy_path(_FIRST_ID))

        with pytest.raises(ToolError, match="folder handle"):
            _ = await _copy(
                client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=folder_ref
            )

        assert copy.call_count == 0

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
    async def test_a_message_ref_that_is_not_a_message_handle_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, message_ref: str
    ) -> None:
        copy = graph.post(_copy_path(_FIRST_ID))

        with pytest.raises(ToolError, match="message handles"):
            _ = await _copy(client, message_refs=[message_ref], destination="archive")

        assert copy.call_count == 0

    async def test_one_bad_handle_stops_the_whole_batch_before_any_of_it_is_copied(
        self, client: GraphServiceClient, first_copy: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="message handles"):
            _ = await _copy(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri, "not-a-handle"],
                destination="archive",
            )

        assert first_copy.call_count == 0

    async def test_an_empty_batch_is_a_programming_error(self, client: GraphServiceClient) -> None:
        with pytest.raises(AssertionError):
            _ = await _copy(client, message_refs=[], destination="archive")


class TestTheSchemaItPublishes:
    async def test_the_batch_needs_one_message_and_has_no_upper_size(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = _properties(await _registered(transport))

        assert properties["message_refs"]["minItems"] == 1
        assert "maxItems" not in properties["message_refs"]

    async def test_only_the_batch_is_required_of_a_client(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.parameters["required"] == ["message_refs"]

    async def test_the_arguments_are_a_plain_object_with_no_combinator_at_the_root(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.parameters["type"] == "object"
        assert not {"anyOf", "oneOf", "allOf", "not"} & set(tool.parameters)
        assert set(_properties(tool)) == {"message_refs", "destination", "folder_ref", "mailbox"}

    async def test_the_confirmation_is_no_argument_of_the_published_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = _properties(await _registered(transport))

        assert "ctx" not in properties
        assert "confirm" not in properties

    async def test_the_destination_vocabulary_is_the_closed_one(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)
        defined = cast("Mapping[str, Mapping[str, object]]", tool.parameters["$defs"])

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
        tool = await _registered(transport)
        defined = cast("Mapping[str, Mapping[str, object]]", tool.parameters["$defs"])
        offered = cast("list[str]", defined["WellKnownFolder"]["enum"])

        assert [name for name in _NEVER_A_DESTINATION if name in offered] == []

    async def test_it_announces_itself_as_a_write_that_adds(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_register_asks_through_the_context_it_is_given(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copies = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))
        tool = await _registered(transport)

        answer = cast(
            "object",
            await tool.fn(
                message_refs=[MailMessageHandle(_FIRST_ID).uri],
                ctx=_modern_context(),
                destination="archive",
                mailbox=_MAILBOX,
                client=client,
            ),
        )

        assert isinstance(answer, InputRequiredResult)
        assert copies.call_count == 0


class TestMailboxTargeting:
    async def test_no_mailbox_copies_mail_in_the_signed_in_users_own_mailbox(
        self, client: GraphServiceClient, archive: respx.Route, first_copy: respx.Route
    ) -> None:
        _ = await _copy(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], folder_ref=_ARCHIVE_REF
        )

        assert archive.called
        assert first_copy.called

    async def test_a_mailbox_copies_mail_in_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        folder = graph.get(f"/users/{_MAILBOX}/mailFolders/{_ARCHIVE_ID}").mock(
            return_value=httpx.Response(200, json=_folder_payload())
        )
        copy = graph.post(_copy_path(_FIRST_ID, owner=f"users/{_MAILBOX}")).mock(
            return_value=_copied(_FIRST_COPY_ID)
        )

        copied = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri],
            folder_ref=_ARCHIVE_REF,
            mailbox=_MAILBOX,
            confirm=_agrees,
        )

        assert folder.called
        assert copy.called
        assert copied.messages[0].copied is True


class TestThePersonBeforeAnotherMailboxIsWrittenTo:
    async def test_the_own_mailbox_asks_nobody_and_copies(
        self, client: GraphServiceClient, first_copy: respx.Route, second_copy: respx.Route
    ) -> None:
        _ = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
            confirm=_never_asked,
        )

        assert (first_copy.call_count, second_copy.call_count) == (1, 1)

    async def test_a_delegated_mailbox_asks_once_for_the_whole_batch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copies = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))
        asked, capturing = _questions()

        _ = await _copy(
            client,
            message_refs=[
                MailMessageHandle(_FIRST_ID).uri,
                MailMessageHandle(_SECOND_ID).uri,
                MailMessageHandle(_THIRD_ID).uri,
            ],
            destination="archive",
            mailbox=_MAILBOX,
            confirm=capturing,
        )

        assert len(asked) == 1
        assert copies.call_count == 3
        assert all(
            path.startswith(f"/v1.0/users/{_MAILBOX}/messages/") and path.endswith("/copy")
            for path in _paths(copies)
        )

    async def test_a_refusal_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copies = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))

        with pytest.raises(ToolError, match=_NOT_COPIED):
            _ = await _copy(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
                destination="archive",
                mailbox=_MAILBOX,
                confirm=_declines,
            )

        assert copies.call_count == 0

    async def test_the_question_for_a_well_known_folder_names_the_mailbox_and_that_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))
        asked, capturing = _questions()

        _ = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri],
            destination="archive",
            mailbox=_MAILBOX,
            confirm=capturing,
        )

        question = asked[0][0]
        assert f"Copy 2 messages in the mailbox '{_MAILBOX}' to the folder 'archive'?" in question
        assert "belongs to someone else" in question

    async def test_the_question_for_one_message_is_in_the_singular(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))
        asked, capturing = _questions()

        _ = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri],
            destination="archive",
            mailbox=_MAILBOX,
            confirm=capturing,
        )

        assert f"Copy 1 message in the mailbox '{_MAILBOX}'" in asked[0][0]

    async def test_the_question_for_a_folder_handle_names_the_folder_graph_reported(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/users/{_MAILBOX}/mailFolders/{_ARCHIVE_ID}").mock(
            return_value=httpx.Response(200, json=_folder_payload(display_name="Invoices 2026"))
        )
        _ = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))
        asked, capturing = _questions()

        _ = await _copy(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri],
            folder_ref=_ARCHIVE_REF,
            mailbox=_MAILBOX,
            confirm=capturing,
        )

        assert "to the folder 'Invoices 2026'?" in asked[0][0]

    async def test_a_very_long_folder_name_is_cut_in_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        long_name = "F" * 300
        _ = graph.get(f"/users/{_MAILBOX}/mailFolders/{_ARCHIVE_ID}").mock(
            return_value=httpx.Response(200, json=_folder_payload(display_name=long_name))
        )
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return _NOT_COPIED

        with pytest.raises(ToolError):
            _ = await _copy(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri],
                folder_ref=_ARCHIVE_REF,
                mailbox=_MAILBOX,
                confirm=capturing,
            )

        assert long_name not in asked[0]
        assert "…" in asked[0]

    async def test_a_folder_that_cannot_receive_mail_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/users/{_MAILBOX}/mailFolders/{_ARCHIVE_ID}").mock(
            return_value=httpx.Response(200, json=_folder_payload(is_hidden=True))
        )
        copies = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))

        with pytest.raises(ToolError, match="hidden"):
            _ = await _copy(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri],
                folder_ref=_ARCHIVE_REF,
                mailbox=_MAILBOX,
                confirm=_never_asked,
            )

        assert copies.call_count == 0

    async def test_a_different_mailbox_folder_or_message_binds_a_different_agreement(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))
        asked, capturing = _questions()

        both = [MailMessageHandle(_FIRST_ID).uri, MailMessageHandle(_SECOND_ID).uri]
        for mailbox, refs, destination in (
            (_MAILBOX, both, "archive"),
            ("sam@example.invalid", both, "archive"),
            (_MAILBOX, both[:1], "archive"),
            (_MAILBOX, both, "inbox"),
        ):
            _ = await _copy(
                client,
                message_refs=refs,
                destination=cast("WellKnownFolder", destination),
                mailbox=mailbox,
                confirm=capturing,
            )

        bound = [about for _question, about in asked]
        assert len({*bound}) == 4
        assert all(question not in about for question, about in asked)

    async def test_the_same_request_binds_the_same_agreement(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))
        asked, capturing = _questions()

        for _ in range(2):
            _ = await _copy(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri],
                destination="archive",
                mailbox=_MAILBOX,
                confirm=capturing,
            )

        assert asked[0][1] == asked[1][1]


def _context(answer: object) -> Context:
    class _Client:
        request_context: object = None

        async def elicit(self, message: str, response_type: object = None) -> object:
            assert message
            assert response_type is not None
            return answer

    return cast("Context", cast("object", _Client()))


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def _modern_context(
    *, answers: Mapping[str, InputResponse] | None = None, state: str | None = None
) -> Context:
    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, InputResponse] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, "
                + f"expecting {response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


def _the_question(answer: copier.MailCopied | InputRequiredResult) -> tuple[str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    assert isinstance(request.params, ElicitRequestFormParams)
    schema = cast("Mapping[str, object]", request.params.requested_schema)
    properties = cast("Mapping[str, Mapping[str, object]]", schema["properties"])
    assert properties["value"]["enum"] == ["copy", "do not copy"]
    assert answer.request_state, "the answer is bound to nothing"
    return key, answer.request_state


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))

        answer = await copier.copy_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri],
            confirm=copier.a_person_agrees(_modern_context()),
            destination="archive",
            mailbox=_MAILBOX,
        )

        _ = _the_question(answer)
        assert _posted(graph) == [], "an unanswered question copied the message anyway"

    async def test_the_second_round_copies_the_messages_it_was_agreed_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copies = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))
        refs = [MailMessageHandle(_FIRST_ID).uri]
        key, state = _the_question(
            await copier.copy_mail(
                client,
                message_refs=refs,
                confirm=copier.a_person_agrees(_modern_context()),
                destination="archive",
                mailbox=_MAILBOX,
            )
        )

        answer = await copier.copy_mail(
            client,
            message_refs=refs,
            confirm=copier.a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "copy"})},
                    state=state,
                )
            ),
            destination="archive",
            mailbox=_MAILBOX,
        )

        assert isinstance(answer, copier.MailCopied)
        assert copies.call_count == 1

    async def test_an_answer_bound_to_other_messages_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))
        key, state = _the_question(
            await copier.copy_mail(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri],
                confirm=copier.a_person_agrees(_modern_context()),
                destination="archive",
                mailbox=_MAILBOX,
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await copier.copy_mail(
                client,
                message_refs=[MailMessageHandle(_SECOND_ID).uri],
                confirm=copier.a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "copy"})},
                        state=state,
                    )
                ),
                destination="archive",
                mailbox=_MAILBOX,
            )

        assert _posted(graph) == []

    async def test_the_own_mailbox_copies_in_one_round(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copies = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))

        answer = await copier.copy_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri],
            confirm=copier.a_person_agrees(_modern_context()),
            destination="archive",
        )

        assert isinstance(answer, copier.MailCopied)
        assert copies.call_count == 1


class TestTheHandshakeEra:
    async def test_an_agreeing_person_gets_the_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copies = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))

        answer = await copier.copy_mail(
            client,
            message_refs=[MailMessageHandle(_FIRST_ID).uri],
            confirm=copier.a_person_agrees(_context(AcceptedElicitation(data="copy"))),
            destination="archive",
            mailbox=_MAILBOX,
        )

        assert isinstance(answer, copier.MailCopied)
        assert copies.call_count == 1

    @pytest.mark.parametrize(
        "answer",
        [DeclinedElicitation(), AcceptedElicitation(data="do not copy")],
        ids=["declined", "another-answer"],
    )
    async def test_a_person_who_does_not_agree_gets_no_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        _ = graph.route(method="POST").mock(return_value=_copied(_FIRST_COPY_ID))

        with pytest.raises(ToolError, match=_NOT_COPIED):
            _ = await copier.copy_mail(
                client,
                message_refs=[MailMessageHandle(_FIRST_ID).uri],
                confirm=copier.a_person_agrees(_context(answer)),
                destination="archive",
                mailbox=_MAILBOX,
            )

        assert _posted(graph) == []


async def _advice(client: GraphServiceClient) -> str:
    advice = GraphAdviceMiddleware(
        {
            copier.TOOL_NAME: ToolAdvice(
                permissions=copier.GRAPH_PERMISSIONS,
                not_found=copier.GRAPH_NOT_FOUND,
                shown_by=copier.CHANGE_SHOWN_BY,
            )
        }
    )

    async def the_tool(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        _ = context
        _ = await _copy(
            client, message_refs=[MailMessageHandle(_FIRST_ID).uri], destination="archive"
        )
        raise AssertionError("Graph refused nothing, so there is no advice to read")

    context = MiddlewareContext(
        message=CallToolRequestParams(
            name=copier.TOOL_NAME,
            arguments={
                "message_refs": [MailMessageHandle(_FIRST_ID).uri],
                "destination": "archive",
            },
        )
    )
    with pytest.raises(ToolError) as raised:
        _ = await advice.on_call_tool(context, the_tool)
    return str(raised.value)


class TestWhatTheModelIsTold:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_an_outage_says_to_look_with_the_two_reads_before_a_second_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_copy_path(_FIRST_ID)).mock(return_value=httpx.Response(503))

        message = await _advice(client)

        assert "Do not call this tool again first." in message
        assert "To see if the change is there, use outlook_read_mail or outlook_list_mail." in (
            message
        )

    async def test_a_message_graph_will_not_return_gets_both_recoveries(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_copy_path(_FIRST_ID)).mock(return_value=_refused(404))

        message = await _advice(client)

        assert "outlook_search_mail" in message
        assert "outlook_browse_folders" in message
        assert "No message was copied." in message


class TestWhatItSaysAboutItself:
    def test_the_permission_is_the_write_one_microsoft_documents(self) -> None:
        assert copier.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

    def test_the_steps_name_the_destination_read_and_the_copy(self) -> None:
        assert copier.STEP_DESTINATION == "destination_folder"
        assert copier.STEP_COPY == "copy_message"

    def test_the_tools_that_show_the_change_are_the_two_mail_reads(self) -> None:
        assert copier.CHANGE_SHOWN_BY == ("outlook_read_mail", "outlook_list_mail")

    async def test_the_description_names_the_agreement_the_sibling_and_what_to_do_after_a_timeout(
        self, transport: httpx.AsyncClient
    ) -> None:
        description = (await _registered(transport)).description or ""

        assert (
            "This tool asks the user to agree before it changes a shared or delegated mailbox. "
            + "It changes the user's own mailbox without a question."
        ) in description
        assert "A copy is a new message, and the original stays where it is." in description
        assert "outlook_move_mail is the tool to move a message instead." in description
        assert "If a call times out, do not call this tool again first." in description
        assert "A second call can make a second copy of each message." in description
        assert "make sure that outlook_list_mail does not show the copies" in description

    async def test_the_description_has_a_lead_a_blank_line_and_up_to_four_notes(
        self, transport: httpx.AsyncClient
    ) -> None:
        description = (await _registered(transport)).description or ""

        lead, _blank, notes = description.partition("\n\nNotes:\n")
        bullets = [line for line in notes.splitlines() if line.startswith("- ")]
        assert lead
        assert 1 <= len(bullets) <= 4
        assert 45 <= len(description.split()) <= 210

    async def test_every_argument_description_is_between_fifteen_and_sixty_words(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        for name, properties in _properties(tool).items():
            words = len(cast("str", properties["description"]).split())
            assert 15 <= words <= 60, f"{name} has {words} words"

    def test_every_answer_field_description_is_between_fifteen_and_sixty_words(self) -> None:
        for model in (copier.CopiedMessage, copier.MailCopied):
            for name, field in model.model_fields.items():
                words = len((field.description or "").split())
                assert 15 <= words <= 60, f"{model.__name__}.{name} has {words} words"

    def test_a_stale_handle_is_answered_with_both_recoveries(self) -> None:
        assert "outlook_browse_folders" in copier.GRAPH_NOT_FOUND
        assert "outlook_search_mail" in copier.GRAPH_NOT_FOUND
        assert "No message was copied." in copier.GRAPH_NOT_FOUND

    def test_a_missing_message_is_never_blamed_on_a_folder_move(self) -> None:
        assert "already moved" not in copier.GRAPH_NOT_FOUND
        assert "A message that moves to another folder of this mailbox keeps its handle." in (
            copier.GRAPH_NOT_FOUND
        )
        assert "Somebody can delete a message permanently, or move it to an archive mailbox." in (
            copier.GRAPH_NOT_FOUND
        )
