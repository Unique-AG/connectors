import asyncio
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from msgraph.generated.models.followup_flag import FollowupFlag
from msgraph.generated.models.followup_flag_status import FollowupFlagStatus
from msgraph.generated.models.message import Message
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphUnavailable,
)
from office_365_mcp.shared.handles import MailFolderHandle, MailMessageHandle
from office_365_mcp.shared.mail import (
    OUTLOOK_FOLDER_NAMES,
    STEP_DESTINATION,
    STEP_OUTLOOK_FOLDER,
    AddressFault,
    MailDestination,
    MailFault,
    MessageAttempt,
    carries_category,
    copied_and_marked,
    destination_asked_for,
    has_flag_state,
    made_by_outlook,
    mail_batch_confirmation_id,
    message_handles,
    one_address_each,
    raise_when_no_message_succeeded,
    repeated_address,
    resolve_destination,
)
from office_365_mcp.shared.seam import graph_mailbox

_ADA = "ada@example.invalid"
_ALEX = "alex@example.invalid"

_FIRST = MailMessageHandle("AAMkAGI2SYNTHETIC-immutable-0001=")
_SECOND = MailMessageHandle("AAMkAGI2SYNTHETIC-immutable-0002=")

_FOLDER_ID = "AQMkADAwSYNTHETIC-folder-0001"
_ROOT_ID = "AQMkADAwSYNTHETIC-msgfolderroot"
_SYNC_ISSUES_ID = "AQMkADAwSYNTHETIC-syncissues"
_INBOX_ID = "AQMkADAwSYNTHETIC-inbox"
_DELETED_ITEMS_ID = "AQMkADAwSYNTHETIC-deleteditems"
_CONFLICTS_ID = "AQMkADAwSYNTHETIC-conflicts"

_FOLDERS = "/me/mailFolders"

_ARCHIVE_ID = "AQMkADAwSYNTHETIC-archive"
_ARCHIVE = MailFolderHandle(_ARCHIVE_ID)
_ARCHIVE_PATH = f"/me/mailFolders/{_ARCHIVE_ID}"

_SEARCH_FOLDER_PROPERTIES: Mapping[str, object] = {
    "filterQuery": "flagStatus eq 'flagged'",
    "sourceFolderIds": ["AQMkADAwSYNTHETIC-inbox"],
    "includeNestedFolders": True,
    "isSupported": True,
}


def _flagged_as(status: FollowupFlagStatus) -> Message:
    return Message(flag=FollowupFlag(flag_status=status))


class TestHasFlagState:
    @pytest.mark.parametrize(
        ("status", "flagged", "matches"),
        [
            (FollowupFlagStatus.Flagged, True, True),
            (FollowupFlagStatus.Flagged, False, False),
            (FollowupFlagStatus.Complete, True, False),
            (FollowupFlagStatus.Complete, False, True),
            (FollowupFlagStatus.NotFlagged, True, False),
            (FollowupFlagStatus.NotFlagged, False, True),
        ],
    )
    def test_only_the_status_flagged_counts_as_flagged(
        self, status: FollowupFlagStatus, flagged: bool, matches: bool
    ) -> None:
        assert has_flag_state(_flagged_as(status), flagged) is matches

    @pytest.mark.parametrize("flagged", [True, False])
    def test_a_message_with_no_flag_matches_neither_value(self, flagged: bool) -> None:
        assert has_flag_state(Message(), flagged) is False


class TestCarriesCategory:
    def test_the_match_ignores_case(self) -> None:
        message = Message(categories=["Red category", "invoices"])

        assert carries_category(message, "INVOICES") is True
        assert carries_category(message, "red CATEGORY") is True

    def test_a_part_of_a_name_is_not_the_name(self) -> None:
        assert carries_category(Message(categories=["Red category"]), "Red") is False

    def test_a_message_with_no_categories_carries_none(self) -> None:
        assert carries_category(Message(), "Invoices") is False
        assert carries_category(Message(categories=[]), "Invoices") is False


class TestCopiedAndMarked:
    def test_nothing_to_say_is_the_empty_text(self) -> None:
        assert copied_and_marked((), importance=None, categories=()) == ""

    def test_each_part_that_is_set_adds_one_sentence(self) -> None:
        said = copied_and_marked(
            ["ada@example.invalid", "bob@example.invalid"],
            importance="high",
            categories=["Invoices", "Red"],
        )

        assert said == (
            " It is copied to ada@example.invalid, bob@example.invalid."
            " It has high importance."
            " It is tagged Invoices, Red."
        )


class TestOnePersonInvitedOnce:
    def test_the_repeat_is_the_entry_that_names_an_address_already_named(self) -> None:
        assert repeated_address([_ADA, _ALEX, _ADA]) == _ADA

    def test_case_is_not_a_second_person(self) -> None:
        assert repeated_address([_ADA, _ADA.upper()]) == _ADA.upper()

    @pytest.mark.parametrize(
        "addresses",
        [[], [_ADA], [_ADA, _ALEX]],
        ids=["nobody", "one-person", "two-people"],
    )
    def test_a_list_that_names_everybody_once_has_no_repeat(self, addresses: list[str]) -> None:
        assert repeated_address(addresses) is None


class TestOneAddressEach:
    def test_plain_addresses_come_back_trimmed_and_in_order(self) -> None:
        assert one_address_each([f"  {_ALEX} ", _ADA]) == (_ALEX, _ADA)

    def test_no_entry_is_no_fault(self) -> None:
        assert one_address_each([]) == ()

    @pytest.mark.parametrize(
        ("entry", "named"),
        [
            ("", ""),
            ("   ", ""),
            ("Ada Lovelace", "Ada Lovelace"),
            (f" Ada Lovelace <{_ADA}> ", f"Ada Lovelace <{_ADA}>"),
            (f"{_ADA}, {_ALEX}", f"{_ADA}, {_ALEX}"),
            (f"{_ADA}; {_ALEX}", f"{_ADA}; {_ALEX}"),
            (f"{_ADA} {_ALEX}", f"{_ADA} {_ALEX}"),
        ],
        ids=[
            "empty",
            "blank",
            "display-name-alone",
            "name-and-angle-brackets",
            "two-with-a-comma",
            "two-with-a-semicolon",
            "two-with-a-space",
        ],
    )
    def test_an_entry_that_is_not_one_address_is_named_as_trimmed(
        self, entry: str, named: str
    ) -> None:
        assert one_address_each([_ALEX, entry]) == AddressFault(entry=named, repeated=False)

    def test_a_repeat_that_differs_only_in_case_is_named_as_written(self) -> None:
        assert one_address_each([_ADA, _ALEX, _ADA.upper()]) == AddressFault(
            entry=_ADA.upper(), repeated=True
        )

    def test_a_repeat_that_differs_only_in_spaces_is_still_a_repeat(self) -> None:
        assert one_address_each([_ADA, f"  {_ADA}"]) == AddressFault(entry=_ADA, repeated=True)

    def test_an_entry_that_is_not_one_address_is_named_before_a_repeat(self) -> None:
        assert one_address_each([_ADA, _ADA, "Ada Lovelace"]) == AddressFault(
            entry="Ada Lovelace", repeated=False
        )


class TestMessageHandles:
    def test_handles_come_back_in_the_order_they_were_given(self) -> None:
        assert message_handles([_SECOND.uri, _FIRST.uri]) == (_SECOND, _FIRST)

    @pytest.mark.parametrize(
        "value",
        [
            "Invoice 4471",
            _ADA,
            _FIRST.message_id,
            _ARCHIVE.uri,
            "https://outlook.office.example/mail/id/AAMkAGI2",
        ],
        ids=["subject", "address", "bare-id", "folder-handle", "web-link"],
    )
    def test_one_value_that_is_no_message_handle_faults_the_whole_batch(self, value: str) -> None:
        assert message_handles([_FIRST.uri, value, _SECOND.uri]) is MailFault.NOT_A_MESSAGE_HANDLE


class TestDestinationAskedFor:
    def test_a_well_known_name_is_the_destination(self) -> None:
        assert destination_asked_for("archive", None) == "archive"

    def test_a_folder_handle_is_parsed(self) -> None:
        assert destination_asked_for(None, _ARCHIVE.uri) == _ARCHIVE

    def test_a_name_and_a_handle_together_are_a_fault(self) -> None:
        assert destination_asked_for("archive", _ARCHIVE.uri) is MailFault.BOTH_DESTINATIONS

    def test_neither_is_a_fault(self) -> None:
        assert destination_asked_for(None, None) is MailFault.NO_DESTINATION

    @pytest.mark.parametrize("value", ["Archive", _FIRST.uri, "archive"])
    def test_a_folder_ref_that_is_no_folder_handle_is_a_fault(self, value: str) -> None:
        assert destination_asked_for(None, value) is MailFault.NOT_A_FOLDER_HANDLE


def _folder(
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


class TestResolveDestination:
    async def test_a_well_known_name_names_itself_and_reads_no_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        found = await resolve_destination(graph_mailbox(client, None), "deleteditems")

        assert found == MailDestination(folder_id="deleteditems", name="deleteditems")
        assert graph.calls.call_count == 0

    async def test_a_folder_handle_is_named_by_the_display_name_graph_reports(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ARCHIVE_PATH).mock(return_value=httpx.Response(200, json=_folder()))

        found = await resolve_destination(graph_mailbox(client, None), _ARCHIVE)

        assert found == MailDestination(folder_id=_ARCHIVE_ID, name="Archive")

    async def test_a_folder_with_no_display_name_is_named_by_its_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ARCHIVE_PATH).mock(
            return_value=httpx.Response(200, json=_folder(display_name=None))
        )

        found = await resolve_destination(graph_mailbox(client, None), _ARCHIVE)

        assert found == MailDestination(folder_id=_ARCHIVE_ID, name=_ARCHIVE.uri)

    async def test_a_mailbox_reads_the_folder_of_that_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        shared = graph.get(f"/users/{_ALEX}/mailFolders/{_ARCHIVE_ID}").mock(
            return_value=httpx.Response(200, json=_folder())
        )
        mine = graph.get(_ARCHIVE_PATH)

        _ = await resolve_destination(graph_mailbox(client, _ALEX), _ARCHIVE)

        assert shared.call_count == 1
        assert mine.call_count == 0

    async def test_a_hidden_folder_is_a_fault(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ARCHIVE_PATH).mock(
            return_value=httpx.Response(200, json=_folder(is_hidden=True))
        )

        found = await resolve_destination(graph_mailbox(client, None), _ARCHIVE)

        assert found is MailFault.HIDDEN_FOLDER

    @pytest.mark.parametrize(
        "payload",
        [
            _folder(odata_type="#microsoft.graph.mailSearchFolder"),
            _folder(extra=_SEARCH_FOLDER_PROPERTIES),
        ],
        ids=["by-odata-type", "by-a-property-only-a-search-folder-has"],
    )
    async def test_a_search_folder_is_a_fault(
        self, client: GraphServiceClient, graph: respx.MockRouter, payload: dict[str, object]
    ) -> None:
        _ = graph.get(_ARCHIVE_PATH).mock(return_value=httpx.Response(200, json=payload))

        found = await resolve_destination(graph_mailbox(client, None), _ARCHIVE)

        assert found is MailFault.SEARCH_FOLDER

    async def test_a_search_folder_that_is_also_hidden_is_a_search_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ARCHIVE_PATH).mock(
            return_value=httpx.Response(
                200, json=_folder(is_hidden=True, odata_type="#microsoft.graph.mailSearchFolder")
            )
        )

        found = await resolve_destination(graph_mailbox(client, None), _ARCHIVE)

        assert found is MailFault.SEARCH_FOLDER

    async def test_a_folder_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ARCHIVE_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await resolve_destination(graph_mailbox(client, None), _ARCHIVE)

    def test_the_graph_step_is_the_one_the_dashboard_knows(self) -> None:
        assert STEP_DESTINATION == "destination_folder"


def _no_such_folder() -> httpx.Response:
    return httpx.Response(
        404, json={"error": {"code": "ErrorItemNotFound", "message": "not found"}}
    )


def _only_these_exist(graph: respx.MockRouter, found: Mapping[str, str]) -> None:
    for name in OUTLOOK_FOLDER_NAMES:
        response = (
            httpx.Response(200, json={"id": found[name]}) if name in found else _no_such_folder()
        )
        _ = graph.get(f"{_FOLDERS}/{name}").mock(return_value=response)


def _read_names(graph: respx.MockRouter) -> list[str]:
    calls = cast("Sequence[Call]", graph.calls)
    return [call.request.url.path.rsplit("/", 1)[-1] for call in calls]


async def _made_by_outlook(
    client: GraphServiceClient, folder_id: str, parent_id: str | None
) -> bool:
    return await made_by_outlook(graph_mailbox(client, None).mail_folders, folder_id, parent_id)


class TestMadeByOutlook:
    def test_the_names_are_the_two_parents_and_the_fifteen_children_and_the_step_is_known(
        self,
    ) -> None:
        assert STEP_OUTLOOK_FOLDER == "mail_folder"
        assert OUTLOOK_FOLDER_NAMES == (
            "msgfolderroot",
            "syncissues",
            "archive",
            "clutter",
            "conflicts",
            "conversationhistory",
            "deleteditems",
            "drafts",
            "inbox",
            "junkemail",
            "localfailures",
            "outbox",
            "recoverableitemsdeletions",
            "scheduled",
            "searchfolders",
            "sentitems",
            "serverfailures",
        )

    @pytest.mark.parametrize(
        ("name", "folder_id"), [("msgfolderroot", _ROOT_ID), ("syncissues", _SYNC_ISSUES_ID)]
    )
    async def test_a_parent_folder_is_refused_after_the_two_parent_lookups(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str, folder_id: str
    ) -> None:
        _only_these_exist(graph, {"msgfolderroot": _ROOT_ID, "syncissues": _SYNC_ISSUES_ID})

        assert await _made_by_outlook(client, folder_id, "above") is True
        assert sorted(_read_names(graph)) == ["msgfolderroot", "syncissues"], name

    async def test_a_top_level_folder_with_the_id_of_the_inbox_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _only_these_exist(graph, {"msgfolderroot": _ROOT_ID, "inbox": _INBOX_ID})

        assert await _made_by_outlook(client, _INBOX_ID, _ROOT_ID) is True

    async def test_a_top_level_folder_with_the_id_of_deleted_items_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _only_these_exist(graph, {"msgfolderroot": _ROOT_ID, "deleteditems": _DELETED_ITEMS_ID})

        assert await _made_by_outlook(client, _DELETED_ITEMS_ID, _ROOT_ID) is True

    async def test_a_child_of_sync_issues_with_the_id_of_conflicts_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _only_these_exist(graph, {"syncissues": _SYNC_ISSUES_ID, "conflicts": _CONFLICTS_ID})

        assert await _made_by_outlook(client, _CONFLICTS_ID, _SYNC_ISSUES_ID) is True

    async def test_a_top_level_user_folder_is_not_refused_after_every_name_is_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        found = {name: f"AQMkADAwSYNTHETIC-{name}" for name in OUTLOOK_FOLDER_NAMES}
        _only_these_exist(graph, found)

        assert await _made_by_outlook(client, _FOLDER_ID, found["msgfolderroot"]) is False
        assert sorted(_read_names(graph)) == sorted(OUTLOOK_FOLDER_NAMES)

    @pytest.mark.parametrize("parent_id", [None, "AQMkADAwSYNTHETIC-folder-0002"])
    async def test_a_nested_folder_makes_only_the_two_parent_lookups(
        self, client: GraphServiceClient, graph: respx.MockRouter, parent_id: str | None
    ) -> None:
        _only_these_exist(graph, {"msgfolderroot": _ROOT_ID, "syncissues": _SYNC_ISSUES_ID})

        assert await _made_by_outlook(client, _FOLDER_ID, parent_id) is False
        assert sorted(_read_names(graph)) == ["msgfolderroot", "syncissues"]

    async def test_a_name_that_answers_not_found_is_skipped_and_the_others_are_still_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _only_these_exist(graph, {"msgfolderroot": _ROOT_ID, "sentitems": _INBOX_ID})

        assert await _made_by_outlook(client, _INBOX_ID, _ROOT_ID) is True
        read = _read_names(graph)
        assert {"clutter", "archive", "sentitems"} <= set(read)

    async def test_a_failure_that_is_not_a_not_found_is_raised(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _only_these_exist(graph, {"msgfolderroot": _ROOT_ID})
        _ = graph.get(f"{_FOLDERS}/clutter").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _made_by_outlook(client, _FOLDER_ID, _ROOT_ID)

    async def test_at_most_four_lookups_are_in_flight_at_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        open_calls = 0
        most_open = 0

        async def answering(request: httpx.Request) -> httpx.Response:
            nonlocal open_calls, most_open
            open_calls += 1
            most_open = max(most_open, open_calls)
            await asyncio.sleep(0.01)
            open_calls -= 1
            if request.url.path.endswith("/msgfolderroot"):
                return httpx.Response(200, json={"id": _ROOT_ID})
            return _no_such_folder()

        lookups = graph.get(path__regex=rf"{_FOLDERS}/[a-z]+$").mock(side_effect=answering)

        assert await _made_by_outlook(client, _FOLDER_ID, _ROOT_ID) is False

        assert lookups.call_count == len(OUTLOOK_FOLDER_NAMES)
        assert most_open == 4


_ARCHIVE_TARGET = MailDestination(folder_id="archive", name="archive")


def _binding(
    *,
    tool_name: str = "outlook_move_mail",
    mailbox: str = _ALEX,
    handles: Sequence[MailMessageHandle] = (_FIRST, _SECOND),
    target: MailDestination = _ARCHIVE_TARGET,
) -> str:
    return mail_batch_confirmation_id(tool_name, mailbox=mailbox, handles=handles, target=target)


class TestMailBatchConfirmationId:
    def test_the_same_request_binds_the_same_id(self) -> None:
        assert _binding() == _binding()

    def test_the_tool_that_asks_is_part_of_the_binding(self) -> None:
        assert _binding(tool_name="outlook_move_mail") != _binding(tool_name="outlook_copy_mail")

    def test_a_different_mailbox_message_or_folder_binds_a_different_id(self) -> None:
        bound = {
            _binding(),
            _binding(mailbox="sam@example.invalid"),
            _binding(handles=(_FIRST,)),
            _binding(handles=(_SECOND, _FIRST)),
            _binding(target=MailDestination(folder_id="inbox", name="inbox")),
        }

        assert len(bound) == 5


_NO_FAILURE = MessageAttempt(result="done", failure=None)


def _failed(failure: GraphFailure) -> MessageAttempt[str]:
    return MessageAttempt(result="failed", failure=failure)


class TestRaiseWhenNoMessageSucceeded:
    def test_one_success_among_failures_raises_nothing(self) -> None:
        outage = GraphUnavailable("down", status=503, code=None, request_id=None)

        raise_when_no_message_succeeded([_failed(outage), _NO_FAILURE, _failed(outage)])

    def test_a_batch_that_all_succeeded_raises_nothing(self) -> None:
        raise_when_no_message_succeeded([_NO_FAILURE, _NO_FAILURE])

    def test_a_batch_that_all_failed_raises_the_first_failure(self) -> None:
        first = GraphNotFound("gone", status=404, code=None, request_id=None)
        second = GraphUnavailable("down", status=503, code=None, request_id=None)

        with pytest.raises(GraphNotFound) as raised:
            raise_when_no_message_succeeded([_failed(first), _failed(second)])

        assert raised.value is first
