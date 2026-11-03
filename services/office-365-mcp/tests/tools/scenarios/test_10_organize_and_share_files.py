import functools
import json
from collections.abc import Mapping, Sequence
from typing import Never, cast

import httpx
import pytest
import respx
from azure.core.exceptions import ClientAuthenticationError
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from respx.models import Call

from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle
from tests.conftest import RecordedSleeps
from tests.e2e.test_scenarios import build_server, patch_obo
from tests.tools.scenarios.support import Person, call, serve

type Row = dict[str, object]
type Failure = httpx.Response | Exception
type Routes = dict[tuple[str, str], respx.Route]

_DRIVE = "b!SYNTHETICDRIVE"
_OTHER_DRIVE = "b!SYNTHETICOTHERDRIVE"
_DRIVE_PATH = "b%21SYNTHETICDRIVE"
_ITEM = "01SYNTHETICITEM"
_FOLDER_ID = "01SYNTHETICFOLDER"
_ARCHIVE_ID = "01SYNTHETICARCHIVE"
_FILE = DriveFileHandle(_DRIVE, _ITEM).uri
_FOLDER = DriveFolderHandle(_DRIVE, _FOLDER_ID).uri
_ARCHIVE = DriveFolderHandle(_DRIVE, _ARCHIVE_ID).uri
_ITEM_PATH = f"/drives/{_DRIVE_PATH}/items/{_ITEM}"
_FOLDER_PATH = f"/drives/{_DRIVE_PATH}/items/{_FOLDER_ID}"
_ARCHIVE_PATH = f"/drives/{_DRIVE_PATH}/items/{_ARCHIVE_ID}"
_NEW_FILE = r".*/items/01SYNTHETICFOLDER:/.*:/content"
_BUSY = {"error": {"code": "activityLimitReached", "message": "busy"}}
_TAKEN = {"error": {"code": "nameAlreadyExists", "message": "taken"}}
_NOTES = "Agenda\nDecision one\nDecision two"
_TOP_OF_A_LIBRARY = {"id": "ROOT", "name": "root", "root": {}, "folder": {"childCount": 3}}
_NOT_CONFIRMED = "say that the request was not confirmed"


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


def _entry(
    item_id: str = _ITEM,
    *,
    name: str = "Plan v1.docx",
    folder: bool = False,
    parent: str = _FOLDER_ID,
    drive: str = _DRIVE,
) -> Row:
    return {
        "id": item_id,
        "name": name,
        "webUrl": f"https://contoso.sharepoint.invalid/{name}",
        "parentReference": {"driveId": drive, "id": parent, "path": "/drive/root:/Projects"},
        **({"folder": {"childCount": 2}} if folder else {"file": {"mimeType": "text/plain"}}),
    }


def _items(graph: respx.MockRouter, **named: Row) -> None:
    paths = {"item": _ITEM_PATH, "folder": _FOLDER_PATH, "archive": _ARCHIVE_PATH}
    for key, payload in named.items():
        _ = graph.get(paths[key]).mock(return_value=httpx.Response(200, json=payload))


def _put_file(graph: respx.MockRouter) -> respx.Route:
    return graph.route(method="PUT", path__regex=_NEW_FILE)


def _route(graph: respx.MockRouter, method: str, path: str) -> respx.Route:
    return _put_file(graph) if path == _NEW_FILE else getattr(graph, method.lower())(path)


def _folders(graph: respx.MockRouter) -> None:
    _items(
        graph,
        folder=_entry(_FOLDER_ID, name="Notes", folder=True, parent="ROOT"),
        archive=_entry(_ARCHIVE_ID, name="Archive", folder=True, parent="ROOT"),
    )


def _body(route: respx.Route) -> Row:
    sent = cast("Row", json.loads(route.calls.last.request.content))
    return {key: value for key, value in sent.items() if key != "@odata.type"}


def _writes(graph: respx.MockRouter) -> list[str]:
    return [method for method, _ in _sent(graph) if method != "GET"]


def _sent(graph: respx.MockRouter) -> list[tuple[str, str]]:
    return [(c.request.method, c.request.url.path) for c in cast("Sequence[Call]", graph.calls)]


async def _call(tool: str, arguments: Row, *, person: Person | None = None) -> Mapping[str, object]:
    return await call(tool, person=person, **cast("dict[str, Never]", arguments))


def _handles(routes: Routes, method: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for verb, path in routes:
        if verb == method and path.startswith("/drives/") and "/items/" in path:
            drive, rest = path.removeprefix("/drives/").split("/items/", 1)
            found.append((drive, rest.split("/", 1)[0].split(":", 1)[0]))
    return list(dict.fromkeys(found))


def _recorded_name(routes: Routes) -> str:
    [name] = [
        path.split(":/", 1)[1].removesuffix(":/content") for (verb, path) in routes if verb == "PUT"
    ]
    return name


class TestFilingDocuments:
    async def test_a_contract_moves_into_a_new_folder_after_each_approval(
        self, graph: respx.MockRouter
    ) -> None:
        person = Person()
        made = serve(graph, "rec-tool-sharepoint_create_folder-seed-folder")
        [(drive, parent)] = _handles(made, "GET")
        created = await call(
            "sharepoint_create_folder",
            parent=DriveFolderHandle(drive, parent).uri,
            name="2026 Signed",
            person=person,
        )
        graph.routes.clear()
        moves = serve(graph, "rec-tool-sharepoint_move_item-budget")
        _, contract, target = _handles(moves, "GET")

        moved = await call(
            "sharepoint_move_item",
            item=DriveFileHandle(*contract).uri,
            to_folder=DriveFolderHandle(*target).uri,
            person=person,
        )

        [patch] = [route for (verb, _), route in moves.items() if verb == "PATCH"]
        assert _body(patch) == {"parentReference": {"id": target[1]}}
        assert (created["is_folder"], moved["previous_parent_uri"] is not None) == (True, True)
        assert len(person.asked) == 2

    async def test_a_folder_is_copied_into_a_folder_of_another_drive_and_the_original_stays(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_entry(name="Template", folder=True))
        )
        _ = graph.get(f"/drives/b%21SYNTHETICOTHERDRIVE/items/{_FOLDER_ID}").mock(
            return_value=httpx.Response(
                200, json=_entry(_FOLDER_ID, name="Shared", folder=True, drive=_OTHER_DRIVE)
            )
        )
        copy = graph.post(f"{_ITEM_PATH}/copy").mock(return_value=httpx.Response(202))

        started = await call(
            "sharepoint_copy_item",
            item=DriveFolderHandle(_DRIVE, _ITEM).uri,
            to_folder=DriveFolderHandle(_OTHER_DRIVE, _FOLDER_ID).uri,
        )

        assert cast("Row", _body(copy)["parentReference"])["driveId"] == _OTHER_DRIVE
        assert started["name"] == "Template"
        assert _writes(graph) == ["POST"]

    async def test_a_delete_moves_a_file_to_the_recycle_bin_after_the_person_approves(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_delete_item-brochure")
        [(drive, item)] = [h for h in _handles(routes, "DELETE")]
        person = Person()

        gone = await call(
            "sharepoint_delete_item", item=DriveFileHandle(drive, item).uri, person=person
        )

        assert gone["deleted"] is True
        assert "recycle bin" in person.asked[0]
        assert _writes(graph) == ["DELETE"]

    async def test_meeting_notes_are_saved_as_a_new_text_file_after_the_person_approves(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_create_text_file-seed-folder")
        [(drive, folder)] = _handles(routes, "GET")
        person = Person()

        saved = await call(
            "sharepoint_create_text_file",
            folder=DriveFolderHandle(drive, folder).uri,
            name=_recorded_name(routes),
            content=_NOTES,
            person=person,
        )

        [put] = [route for (verb, _), route in routes.items() if verb == "PUT"]
        assert put.calls.last.request.content.decode() == _NOTES
        assert len(person.asked) == 1
        assert saved["is_folder"] is False

    async def test_a_file_is_renamed_and_only_its_name_is_sent(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_rename_item-notes")
        [(drive, item)] = _handles(routes, "GET")
        person = Person()

        renamed = await call(
            "sharepoint_rename_item",
            item=DriveFileHandle(drive, item).uri,
            name="Plan v2.docx",
            person=person,
        )

        [patch] = [route for (verb, _), route in routes.items() if verb == "PATCH"]
        assert _body(patch) == {"name": "Plan v2.docx"}
        assert len(person.asked) == 1
        assert "previous_name" in renamed

    async def test_a_copy_into_the_same_folder_carries_the_new_name(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_copy_item-brochure")
        source, folder = _handles(routes, "GET")[1:3]

        started = await call(
            "sharepoint_copy_item",
            item=DriveFileHandle(*source).uri,
            to_folder=DriveFolderHandle(*folder).uri,
            name="Template copy.docx",
        )

        [copy] = [route for (_, path), route in routes.items() if path.endswith("/copy")]
        assert _body(copy)["name"] == "Template copy.docx"
        assert started["name"] == "Template copy.docx"

    async def test_an_existing_file_is_not_replaced_and_the_tool_offers_no_replace(
        self, graph: respx.MockRouter
    ) -> None:
        _folders(graph)
        put = _put_file(graph).mock(return_value=httpx.Response(409, json=_TAKEN))
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            names = [tool.name for tool in await client.list_tools()]

        with pytest.raises(ToolError) as taken:
            _ = await call(
                "sharepoint_create_text_file", folder=_FOLDER, name="Plan.txt", content="new text"
            )

        assert put.calls.last.request.url.params["@microsoft.graph.conflictBehavior"] == "fail"
        assert "already has the same name" in str(taken.value)
        assert not [n for n in names if n.startswith("sharepoint_") and "replace" in n]

    async def test_a_mail_attachment_cannot_be_saved_because_only_text_files_are_created(
        self, graph: respx.MockRouter
    ) -> None:
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            tools = {tool.name: tool for tool in await client.list_tools()}

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_create_text_file", folder=_FOLDER, name="Offer.pdf", content="%PDF"
            )

        assert "cannot create a Word, Excel, PowerPoint or PDF file" in str(refused.value)
        assert "cannot replace a file or upload a binary file" in (
            tools["sharepoint_create_text_file"].description or ""
        )
        assert not graph.calls


class TestGivingAccess:
    async def test_a_colleague_gets_edit_access_with_an_invitation_after_the_person_approves(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_invite-write-notify")
        drive, item = _handles(routes, "POST")[-1]
        [invite] = [route for (_, path), route in routes.items() if path.endswith("/invite")]
        person = Person()

        shared = await call(
            "sharepoint_invite",
            item=DriveFileHandle(drive, item).uri,
            recipients=["anna@example.test"],
            role="write",
            person=person,
        )

        [anna] = cast("list[Row]", shared["recipients"])
        assert (anna["display_name"], anna["roles"]) == ("Anna Meier", ["write"])
        assert _body(invite)["recipients"] == [{"email": "anna@example.test"}]
        assert _body(invite)["sendInvitation"] is True
        assert len(person.asked) == 1
        assert "edit access" in person.asked[0]

    async def test_a_view_link_is_created_after_the_person_approves_and_sent_to_nobody(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_create_share_link-plan")
        [(drive, item)] = _handles(routes, "POST")
        person = Person()

        link = await call(
            "sharepoint_create_share_link",
            item=DriveFileHandle(drive, item).uri,
            access="view",
            person=person,
        )

        [create] = [route for (_, path), route in routes.items() if path.endswith("createLink")]
        assert _body(create)["type"] == "view"
        assert str(link["share_url"]).startswith("https://")
        assert len(person.asked) == 1
        assert not [path for _, path in _sent(graph) if path.endswith(("invite", "sendMail"))]

    async def test_access_cannot_be_taken_back_because_no_tool_removes_it(self) -> None:
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            tools = {tool.name: tool for tool in await client.list_tools()}

        sharing = [name for name in tools if name.startswith("sharepoint_")]
        assert not [
            name for name in sharing if any(w in name for w in ("remove", "revoke", "unshare"))
        ]
        assert "No tool here can remove the access" in (
            tools["sharepoint_invite"].description or ""
        )

    async def test_a_note_of_exactly_2000_characters_goes_out_with_the_invitation(
        self, graph: respx.MockRouter
    ) -> None:
        _items(graph, item=_entry(name="Q3 Plan.pptx"))
        invite = graph.post(f"{_ITEM_PATH}/invite").mock(
            return_value=httpx.Response(200, json={"value": []})
        )

        _ = await call(
            "sharepoint_invite",
            item=_FILE,
            recipients=["anna@example.invalid"],
            role="write",
            message="n" * 2000,
        )

        assert len(cast("str", _body(invite)["message"])) == 2000

    async def test_a_note_of_2001_characters_stops_the_invitation(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_invite",
                item=_FILE,
                recipients=["anna@example.invalid"],
                role="write",
                message="n" * 2001,
            )

        assert "at most 2000 characters" in str(refused.value)
        assert not graph.calls

    async def test_a_person_named_without_a_mail_address_is_not_invited(
        self, graph: respx.MockRouter
    ) -> None:
        person = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_invite",
                item=_FILE,
                recipients=["Anna at Brightway"],
                role="write",
                person=person,
            )

        assert "not one email address" in str(refused.value)
        assert "Take the address from what the user told you" in str(refused.value)
        assert (graph.calls, person.asked) == ([], [])

    async def test_an_invitation_that_may_be_out_is_sent_once_and_the_app_is_to_be_checked(
        self, graph: respx.MockRouter
    ) -> None:
        _items(graph, item=_entry(name="Q3 Plan.pptx"))
        invite = graph.post(f"{_ITEM_PATH}/invite").mock(side_effect=httpx.ReadTimeout("injected"))

        with pytest.raises(ToolError) as unknown:
            _ = await call(
                "sharepoint_invite", item=_FILE, recipients=["anna@example.invalid"], role="write"
            )

        assert invite.call_count == 1
        assert "does not know if Microsoft 365 made the change" in str(unknown.value)
        assert "ask the user if the Microsoft 365 app shows the change" in str(unknown.value)

    async def test_a_link_without_sign_in_that_the_organization_blocks_is_explained(
        self, graph: respx.MockRouter
    ) -> None:
        _items(graph, item=_entry(name="Q3 Plan.pptx"))
        link = graph.post(f"{_ITEM_PATH}/createLink").mock(
            return_value=httpx.Response(403, json=_BUSY)
        )

        with pytest.raises(ToolError) as blocked:
            _ = await call(
                "sharepoint_create_share_link", item=_FILE, access="view", audience="anonymous"
            )

        assert link.call_count == 1
        assert "An administrator can block links that work with no sign-in" in str(blocked.value)
        assert "ask the user if a link for the organization is enough" in str(blocked.value)


class TestASaveThatFails:
    @pytest.mark.parametrize(
        ("status", "told"),
        [
            (401, "Ask the user to sign in to this connector again"),
            (404, "Find the folder again with sharepoint_search_files or sharepoint_browse_folder"),
        ],
        ids=["sign-in-expired", "folder-gone"],
    )
    async def test_a_folder_that_microsoft_will_not_open_creates_no_file(
        self, graph: respx.MockRouter, status: int, told: str
    ) -> None:
        _ = graph.get(_FOLDER_PATH).mock(return_value=httpx.Response(status, json=_BUSY))
        put = _put_file(graph)
        person = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_create_text_file",
                folder=_FOLDER,
                name="Sync.txt",
                content=_NOTES,
                person=person,
            )

        assert told in str(refused.value)
        assert (put.called, person.asked) == (False, [])

    async def test_a_file_that_microsoft_refuses_to_save_is_explained_after_the_approval(
        self, graph: respx.MockRouter
    ) -> None:
        _folders(graph)
        put = _put_file(graph).mock(return_value=httpx.Response(403, json=_BUSY))
        person = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_create_text_file",
                folder=_FOLDER,
                name="Sync.txt",
                content=_NOTES,
                person=person,
            )

        assert len(person.asked) == 1
        assert put.call_count == 1
        assert "can lack the necessary access" in str(refused.value)
        assert "A policy of the organization can also refuse the request" in str(refused.value)
        assert "The owner of the item can give the user more access" in str(refused.value)

    @pytest.mark.parametrize(
        ("tool", "arguments", "route"),
        [
            (
                "sharepoint_create_text_file",
                {"folder": _FOLDER, "name": "Sync.txt", "content": _NOTES},
                ("PUT", _NEW_FILE),
            ),
            (
                "sharepoint_create_folder",
                {"parent": _FOLDER, "name": "2026 Signed"},
                ("POST", f"{_FOLDER_PATH}/children"),
            ),
        ],
        ids=["file", "folder"],
    )
    async def test_a_name_that_is_already_used_creates_nothing_more(
        self, graph: respx.MockRouter, tool: str, arguments: Row, route: tuple[str, str]
    ) -> None:
        _folders(graph)
        write = _route(graph, *route).mock(return_value=httpx.Response(409, json=_TAKEN))

        with pytest.raises(ToolError) as taken:
            _ = await _call(tool, arguments)

        assert write.call_count == 1
        assert "already has the same name" in str(taken.value)
        assert "Change the name" in str(taken.value)

    async def test_a_busy_microsoft_is_given_the_time_it_asks_for_and_the_save_is_sent_once(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        _folders(graph)
        put = _put_file(graph).mock(
            return_value=httpx.Response(429, headers={"retry-after": "30"}, json=_BUSY)
        )

        with pytest.raises(ToolError) as busy:
            _ = await call(
                "sharepoint_create_text_file", folder=_FOLDER, name="Sync.txt", content=_NOTES
            )

        assert "asked to be left alone for 30 seconds" in str(busy.value)
        assert (put.call_count, retry_sleeps.delays) == (1, [])

    @pytest.mark.parametrize(
        ("tool", "arguments", "route"),
        [
            (
                "sharepoint_create_text_file",
                {"folder": _FOLDER, "name": "Sync.txt", "content": _NOTES},
                ("PUT", _NEW_FILE),
            ),
            (
                "sharepoint_create_folder",
                {"parent": _FOLDER, "name": "2026 Signed"},
                ("POST", f"{_FOLDER_PATH}/children"),
            ),
            (
                "sharepoint_copy_item",
                {"item": _FILE, "to_folder": _ARCHIVE},
                ("POST", f"{_ITEM_PATH}/copy"),
            ),
        ],
        ids=["file", "folder", "copy"],
    )
    @pytest.mark.parametrize(
        "failure",
        [httpx.Response(500, json=_BUSY), httpx.ReadTimeout("injected")],
        ids=["internal-error", "no-answer"],
    )
    async def test_a_write_that_microsoft_fails_is_sent_once_and_looked_for_before_a_repeat(
        self,
        graph: respx.MockRouter,
        tool: str,
        arguments: Row,
        route: tuple[str, str],
        failure: Failure,
    ) -> None:
        _folders(graph)
        _items(graph, item=_entry())
        write = _route(graph, *route).mock(side_effect=[failure])

        with pytest.raises(ToolError) as unknown:
            _ = await _call(tool, arguments)

        assert write.call_count == 1
        assert "does not know if Microsoft 365 made the change" in str(unknown.value)
        assert "sharepoint_browse_folder" in str(unknown.value)

    async def test_a_file_that_was_saved_but_cannot_be_shown_is_not_saved_twice(
        self, graph: respx.MockRouter
    ) -> None:
        _folders(graph)
        put = _put_file(graph).mock(return_value=httpx.Response(201, json={}))

        with pytest.raises(ToolError) as unread:
            _ = await call(
                "sharepoint_create_text_file", folder=_FOLDER, name="Sync.txt", content=_NOTES
            )

        assert put.call_count == 1
        assert "Do not call this tool again for this file" in str(unread.value)
        assert "Use sharepoint_browse_folder on the same `folder`" in str(unread.value)

    async def test_a_rejected_save_gives_the_reason_and_is_not_repeated(
        self, graph: respx.MockRouter
    ) -> None:
        _folders(graph)
        reason = {"error": {"code": "invalidRequest", "message": "the path is too long"}}
        put = _put_file(graph).mock(return_value=httpx.Response(400, json=reason))

        with pytest.raises(ToolError) as rejected:
            _ = await call(
                "sharepoint_create_text_file", folder=_FOLDER, name="Sync.txt", content=_NOTES
            )

        assert put.call_count == 1
        assert "the path is too long" in str(rejected.value)
        assert "will fail the same way" in str(rejected.value)

    @pytest.mark.parametrize(
        "failure",
        [httpx.Response(500, json=_BUSY), httpx.ReadTimeout("injected")],
        ids=["internal-error", "no-answer"],
    )
    async def test_a_move_that_microsoft_fails_is_tried_once_more_and_asked_again(
        self, graph: respx.MockRouter, failure: Failure
    ) -> None:
        _items(
            graph,
            item=_entry(name="Q3 Plan.pptx"),
            archive=_entry(_ARCHIVE_ID, name="Archive", folder=True, parent="ROOT"),
        )
        patch = graph.patch(_ITEM_PATH).mock(
            side_effect=[
                failure,
                httpx.Response(200, json=_entry(name="Q3 Plan.pptx", parent=_ARCHIVE_ID)),
            ]
        )
        person = Person()

        with pytest.raises(ToolError) as first:
            _ = await call("sharepoint_move_item", item=_FILE, to_folder=_ARCHIVE, person=person)
        second = await call("sharepoint_move_item", item=_FILE, to_folder=_ARCHIVE, person=person)

        assert "Retry once" in str(first.value)
        assert (patch.call_count, len(person.asked)) == (2, 2)
        assert cast("Row", second["item"])["parent_uri"] == _ARCHIVE


class TestAChangeThatIsRefusedBeforeAnythingHappens:
    @pytest.mark.parametrize(
        ("name", "sign"),
        [("Sync: 14 June.txt", "`:`"), ("Notes?.txt", "`?`"), ("~$Sync.txt", "`~$`")],
        ids=["colon", "question-mark", "tilde-dollar"],
    )
    async def test_a_name_with_a_sign_that_microsoft_does_not_allow_is_refused(
        self, graph: respx.MockRouter, name: str, sign: str
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call("sharepoint_create_text_file", folder=_FOLDER, name=name, content=_NOTES)

        assert sign in str(refused.value)
        assert not graph.calls

    @pytest.mark.parametrize(
        "name", ["Sync 14 June.docx", "Budget.xlsx", "Offer.pdf", "Sync 14 June"]
    )
    async def test_a_name_that_is_not_a_text_file_is_refused(
        self, graph: respx.MockRouter, name: str
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call("sharepoint_create_text_file", folder=_FOLDER, name=name, content=_NOTES)

        assert "writes text only" in str(refused.value)
        assert "cannot create a Word, Excel, PowerPoint or PDF file" in str(refused.value)
        assert not graph.calls

    async def test_a_text_of_exactly_one_million_characters_is_saved_whole(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_create_text_file-one-million")
        [(drive, folder)] = _handles(routes, "GET")
        [put] = [route for (verb, _), route in routes.items() if verb == "PUT"]

        saved = await call(
            "sharepoint_create_text_file",
            folder=DriveFolderHandle(drive, folder).uri,
            name=_recorded_name(routes),
            content="x" * 1_000_000,
        )

        assert len(put.calls.last.request.content) == 1_000_000
        assert saved["is_folder"] is False

    async def test_a_text_of_one_million_and_one_characters_is_refused(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_create_text_file",
                folder=_FOLDER,
                name="Log.txt",
                content="x" * 1_000_001,
            )

        assert "at most 1000000 characters" in str(refused.value)
        assert not graph.calls

    @pytest.mark.parametrize(
        ("tool", "arguments", "instead"),
        [
            (
                "sharepoint_move_item",
                {"item": _FILE, "to_folder": _ARCHIVE},
                "move each item inside it",
            ),
            (
                "sharepoint_rename_item",
                {"item": _FILE, "name": "Other"},
                "Rename a file or a folder inside the drive instead",
            ),
            (
                "sharepoint_copy_item",
                {"item": _FILE, "to_folder": _ARCHIVE},
                "copy the items inside it one at a time",
            ),
            ("sharepoint_delete_item", {"item": _FILE}, "pass the handle of that item"),
        ],
        ids=["move", "rename", "copy", "delete"],
    )
    async def test_the_top_folder_of_a_library_is_not_changed(
        self, graph: respx.MockRouter, tool: str, arguments: Row, instead: str
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_TOP_OF_A_LIBRARY))
        _ = graph.get(_ARCHIVE_PATH).mock(
            return_value=httpx.Response(200, json=_entry(_ARCHIVE_ID, name="Archive", folder=True))
        )
        person = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, arguments, person=person)

        assert instead in str(refused.value)
        assert (_writes(graph), person.asked) == ([], [])

    async def test_a_move_to_another_drive_is_refused_with_the_copy_then_delete_advice(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_move_item",
                item=_FILE,
                to_folder=DriveFolderHandle(_OTHER_DRIVE, _FOLDER_ID).uri,
            )

        assert "copy it with sharepoint_copy_item" in str(refused.value)
        assert "the copy has only the latest version of a file" in str(refused.value)
        assert "use sharepoint_delete_item on the original" in str(refused.value)
        assert not graph.calls

    async def test_a_file_that_is_already_in_the_folder_is_not_moved(
        self, graph: respx.MockRouter
    ) -> None:
        _items(
            graph,
            item=_entry(parent=_ARCHIVE_ID),
            archive=_entry(_ARCHIVE_ID, name="Archive", folder=True),
        )
        person = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call("sharepoint_move_item", item=_FILE, to_folder=_ARCHIVE, person=person)

        assert "The item is already in the folder" in str(refused.value)
        assert (_writes(graph), person.asked) == ([], [])

    async def test_a_file_that_is_already_gone_is_not_deleted_again(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(404, json=_BUSY))
        person = Person()

        with pytest.raises(ToolError) as gone:
            _ = await call("sharepoint_delete_item", item=_FILE, person=person)

        assert "is probably already gone" in str(gone.value)
        assert "it is already gone and nothing is left to delete" in str(gone.value)
        assert (_writes(graph), person.asked) == ([], [])

    async def test_a_missing_consent_is_explained_and_nothing_is_moved(
        self, graph: respx.MockRouter
    ) -> None:
        async def refuse(_self: AzureProvider, **_: object) -> object:
            raise ClientAuthenticationError("AADSTS65001: the administrator never consented")

        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            patch.setattr(AzureProvider, "get_obo_credential", refuse)
            async with Client(FastMCPTransport(_server()), mode="legacy") as client:
                with pytest.raises(ToolError) as refused:
                    _ = await client.call_tool(
                        "sharepoint_move_item", {"item": _FILE, "to_folder": _ARCHIVE}
                    )

        assert "ask a Microsoft 365 administrator to grant" in str(refused.value)
        assert "sign in to this connector again" in str(refused.value)
        assert not graph.calls


_WRITES: list[tuple[str, Row]] = [
    ("sharepoint_move_item", {"item": _FILE, "to_folder": _ARCHIVE}),
    ("sharepoint_delete_item", {"item": _FILE}),
    ("sharepoint_rename_item", {"item": _FILE, "name": "Plan v2.docx"}),
    ("sharepoint_invite", {"item": _FILE, "recipients": ["anna@example.invalid"], "role": "write"}),
    ("sharepoint_create_text_file", {"folder": _FOLDER, "name": "Sync.txt", "content": _NOTES}),
]
_WRITE_IDS = ["move", "delete", "rename", "invite", "save"]


class TestAChangeThatIsNotApproved:
    @pytest.mark.parametrize(("tool", "arguments"), _WRITES, ids=_WRITE_IDS)
    async def test_a_declined_change_leaves_everything_as_it_was(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        _folders(graph)
        _items(graph, item=_entry())
        person = Person(approval="no")

        with pytest.raises(ToolError) as declined:
            _ = await _call(tool, arguments, person=person)

        assert _NOT_CONFIRMED in str(declined.value)
        assert "Do not call this tool again for the same request" in str(declined.value)
        assert (len(person.asked), _writes(graph)) == (1, [])

    @pytest.mark.parametrize(("tool", "arguments"), _WRITES, ids=_WRITE_IDS)
    async def test_a_change_without_an_answer_does_not_happen_and_can_be_asked_again(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        _folders(graph)
        _items(graph, item=_entry())
        person = Person(approval="unanswered")

        with pytest.raises(ToolError) as unanswered:
            _ = await _call(tool, arguments, person=person)

        assert "received no answer" in str(unanswered.value)
        assert "they can make the same request again" in str(unanswered.value)
        assert _writes(graph) == []
