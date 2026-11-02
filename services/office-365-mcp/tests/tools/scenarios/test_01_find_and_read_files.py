import base64
import functools
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
import respx
from azure.core.exceptions import ClientAuthenticationError
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from mcp.types import BlobResourceContents, EmbeddedResource, TextResourceContents

from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle
from tests.conftest import RecordedSleeps
from tests.e2e.test_scenarios import build_server, patch_obo
from tests.tools.conftest import search_response
from tests.tools.scenarios.support import call, serve

type Row = dict[str, object]

_DRIVE = "b%21SYNTHETICDRIVE"
_FILE_ID = "01SYNTHETICFILE"
_FOLDER_ID = "01SYNTHETICFOLDER"
_FILE = DriveFileHandle("b!SYNTHETICDRIVE", _FILE_ID).uri
_FOLDER = DriveFolderHandle("b!SYNTHETICDRIVE", _FOLDER_ID).uri
_ITEM_PATH = f"/drives/{_DRIVE}/items/{_FILE_ID}"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PDF = "application/pdf"
_MEGABYTE = 1024 * 1024
_FIRST_EDIT = datetime(2026, 1, 1, tzinfo=UTC)
_BUSY = {"error": {"code": "activityLimitReached", "message": "busy"}}
_REJECTED = {
    "error": {"code": "invalidRequest", "message": "the item is not valid for this operation"}
}


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


async def _read(file: str = _FILE, **arguments: object) -> tuple[str, bytes]:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            answer = await client.call_tool("sharepoint_read_file", {"file": file, **arguments})
    [block] = answer.content
    assert isinstance(block, EmbeddedResource)
    resource = block.resource
    if isinstance(resource, TextResourceContents):
        return resource.mime_type or "", resource.text.encode()
    assert isinstance(resource, BlobResourceContents)
    return resource.mime_type or "", base64.b64decode(resource.blob)


def _rows(answer: Mapping[str, object], key: str) -> list[Row]:
    return cast("list[Row]", answer[key])


def _names(answer: Mapping[str, object], key: str) -> list[object]:
    return [row["name"] for row in _rows(answer, key)]


def _query_string(route: respx.Route) -> str:
    body = cast("Row", json.loads(route.calls.last.request.content))
    request = cast("list[Row]", body["requests"])[0]
    return cast("str", cast("Row", request["query"])["queryString"])


def _hit(
    name: str, *, edited_by: str = "Ada Lovelace", edited: str = "2026-03-04T16:12:41Z"
) -> Row:
    resource = {
        "@odata.type": "#microsoft.graph.driveItem",
        "id": f"01{name}",
        "name": name,
        "size": 2048,
        "webUrl": f"https://contoso.sharepoint.invalid/sites/Legal/{name}",
        "lastModifiedDateTime": edited,
        "lastModifiedBy": {"user": {"displayName": edited_by}},
        "file": {"mimeType": _DOCX},
        "parentReference": {"driveId": "b!SYNTHETICDRIVE", "id": _FOLDER_ID},
    }
    return {"hitId": name, "rank": 1, "summary": "synthetic", "resource": resource}


def _item(
    facets: Mapping[str, object] | None = None, *, size: int | None = 4, mime_type: str = _PDF
) -> Row:
    return {
        "id": _FILE_ID,
        "name": "Brightway Launch Plan.pdf",
        "size": size,
        "webUrl": "https://contoso.sharepoint.invalid/sites/Sales/Brightway.pdf",
        "parentReference": {"driveId": "b!SYNTHETICDRIVE"},
        **(facets or {"file": {"mimeType": mime_type}}),
    }


def _child(name: str, *, folder: bool, modified: str) -> Row:
    return {
        "id": f"01{name}",
        "name": name,
        "size": 100,
        "lastModifiedDateTime": modified,
        "parentReference": {"driveId": "b!SYNTHETICDRIVE"},
        **({"folder": {"childCount": 7}} if folder else {"file": {"mimeType": _PDF}}),
    }


def _item_path(handle: str) -> str:
    drive, item = handle.rsplit("/", 2)[-2:]
    return f"/drives/{drive}/items/{item}"


def _serve_file(
    graph: respx.MockRouter,
    content: bytes = b"%PDF-1.7 launch 14 June",
    *,
    handle: str = _FILE,
    mime_type: str = _PDF,
) -> respx.Route:
    path = _item_path(handle)
    _ = graph.get(path).mock(
        return_value=httpx.Response(200, json=_item(size=len(content), mime_type=mime_type))
    )
    return graph.get(f"{path}/content").mock(return_value=httpx.Response(200, content=content))


def _serve_children(
    graph: respx.MockRouter, *children: Row, folder: str = _FOLDER, next_link: str | None = None
) -> respx.Route:
    drive, item = folder.rsplit("/", 2)[-2:]
    body: Row = {"value": list(children)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return graph.get(f"/drives/{drive}/items/{item}/children").mock(
        return_value=httpx.Response(200, json=body)
    )


class TestFindingAFile:
    async def test_a_search_by_word_and_type_asks_for_that_type_and_shows_the_hit(
        self, graph: respx.MockRouter
    ) -> None:
        route = serve(graph, "rec-tool-sharepoint_search_files-plan")[("POST", "/search/query")]

        found = await call(
            "sharepoint_search_files", query="seed-v1 Project Plan", file_type="docx"
        )

        assert _names(found, "files") == ["seed-v1 Project Plan.docx"]
        assert "filetype:docx" in _query_string(route)

    async def test_the_file_edited_last_comes_first_with_its_editor(
        self, graph: respx.MockRouter
    ) -> None:
        may = _hit("Plan May.docx", edited_by="Priya", edited="2026-05-12T09:00:00Z")
        march = _hit("Plan March.docx", edited_by="Tom", edited="2026-03-12T09:00:00Z")
        january = _hit("Plan January.docx", edited_by="Anna", edited="2026-01-12T09:00:00Z")
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([may, march, january]))
        )

        found = await call(
            "sharepoint_search_files", query="quarterly plan", sort_by="last_modified"
        )

        first = _rows(found, "files")[0]
        assert (first["name"], first["last_modified_by"]) == ("Plan May.docx", "Priya")
        sent = cast(
            "list[Row]", cast("Row", json.loads(route.calls.last.request.content))["requests"]
        )
        assert sent[0]["sortProperties"] == [{"name": "LastModifiedTime", "isDescending": True}]

    async def test_a_search_stays_on_the_site_that_a_site_search_named(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_search_sites-all")
        routes |= serve(graph, "rec-tool-sharepoint_search_files-plan")

        sites = await call("sharepoint_search_sites", query="Legal")
        site = cast("str", _rows(sites, "sites")[2]["web_url"])
        _ = await call("sharepoint_search_files", query="NDA Template", path=site)

        assert f'path:"{site}"' in _query_string(routes[("POST", "/search/query")])

    async def test_files_that_changed_in_a_window_are_asked_for_with_that_window(
        self, graph: respx.MockRouter
    ) -> None:
        route = serve(graph, "rec-tool-sharepoint_search_files-plan")[("POST", "/search/query")]

        found = await call(
            "sharepoint_search_files",
            query="Brightway",
            modified_after="2026-10-26",
            modified_before="2026-10-30",
        )

        assert len(_rows(found, "files")) == 1
        asked = _query_string(route)
        assert "LastModifiedTime>=2026-10-26T00:00:00Z" in asked
        assert "LastModifiedTime<2026-10-31T00:00:00Z" in asked

    async def test_a_search_without_a_match_answers_with_an_empty_list(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        found = await call("sharepoint_search_files", query="Zephyr")

        assert (found["files"], found["next_offset"]) == ([], None)


class TestBrowsingAFolder:
    async def test_a_folder_lists_one_level_newest_first(self, graph: respx.MockRouter) -> None:
        route = _serve_children(
            graph,
            _child("A Oldest.pdf", folder=False, modified="2026-01-01T00:00:00Z"),
            _child("B Newest.pdf", folder=False, modified="2026-03-01T00:00:00Z"),
            _child("C Subfolder", folder=True, modified="2026-02-01T00:00:00Z"),
        )

        level = await call("sharepoint_browse_folder", folder=_FOLDER, order_by="last_modified")

        assert _names(level, "items") == ["B Newest.pdf", "C Subfolder", "A Oldest.pdf"]
        assert level["order_covers_level"] is True
        assert route.call_count == 1, "nothing inside the subfolder is listed"

    async def test_the_top_of_onedrive_lists_its_files_and_folders(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_browse_folder-root")

        level = await call("sharepoint_browse_folder")

        assert len(_rows(level, "items")) == 6
        assert {row["is_folder"] for row in _rows(level, "items")} == {True}
        assert level["capped"] is False
        assert [route.call_count for route in routes.values()] == [1, 1]

    async def test_the_files_of_a_channel_are_listed_from_its_files_folder(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-teams_get_channel_files_folder-standard")
        teams = await call("teams_list_my_teams")
        team = cast("str", _rows(teams, "teams")[0]["team_id"])
        channels = await call("teams_list_channels", team_id=team)
        channel = cast("str", _rows(channels, "channels")[0]["channel_id"])
        folder = await call("teams_get_channel_files_folder", team_id=team, channel_id=channel)
        files_folder = cast("str", folder["uri"])
        _ = _serve_children(
            graph,
            _child("Launch Plan.docx", folder=False, modified="2026-03-01T00:00:00Z"),
            folder=files_folder,
        )

        listed = await call("sharepoint_browse_folder", folder=files_folder)

        assert _names(listed, "items") == ["Launch Plan.docx"]


_SHARING_LINK = (
    "https://contoso-my.sharepoint.com/personal/mia_example_test/Documents/"
    + "seed-v1%20Seed%20Files/seed-v1%20Project%20Plan.docx"
)


class TestReadingAFile:
    @pytest.mark.parametrize(
        ("mime_type", "content"),
        [(_PDF, b"%PDF-1.7 launch 14 June"), ("text/plain", b"the launch date is 14 June")],
        ids=["pdf", "plain-text"],
    )
    async def test_a_file_that_needs_no_conversion_comes_back_as_it_is(
        self, graph: respx.MockRouter, mime_type: str, content: bytes
    ) -> None:
        asked = _serve_file(graph, content, mime_type=mime_type)

        assert await _read(_FILE) == (mime_type, content)
        assert asked.calls.last.request.url.params == httpx.QueryParams()

    async def test_a_sharing_link_leads_to_the_file_it_opens(self, graph: respx.MockRouter) -> None:
        _ = serve(graph, "rec-tool-sharepoint_resolve_url-plan")

        opened = await call("sharepoint_resolve_url", url=_SHARING_LINK)
        _ = _serve_file(graph, b"PK Q3 plan", handle=cast("str", opened["uri"]), mime_type=_DOCX)

        assert opened["name"] == "seed-v1 Project Plan.docx"
        assert await _read(cast("str", opened["uri"])) == (_DOCX, b"PK Q3 plan")

    async def test_a_pasted_address_that_opens_nothing_sends_the_assistant_to_the_search(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-sharepoint_resolve_url-plan")
        [lookup] = [route for (_, path), route in routes.items() if path.startswith("/shares/")]
        _ = lookup.mock(return_value=httpx.Response(404, json={"error": {"code": "itemNotFound"}}))

        with pytest.raises(ToolError) as lookup_failed:
            _ = await call("sharepoint_resolve_url", url=_SHARING_LINK)
        found = await call("sharepoint_search_files", query="seed-v1 Project Plan")
        _ = _serve_file(graph, b"PK Q3 plan", handle=cast("str", _rows(found, "files")[0]["uri"]))

        assert "sharepoint_search_files" in str(lookup_failed.value)
        assert (await _read(cast("str", _rows(found, "files")[0]["uri"])))[1] == b"PK Q3 plan"

    async def test_every_file_of_a_folder_is_read_on_its_own(self, graph: respx.MockRouter) -> None:
        _ = serve(graph, "rec-tool-sharepoint_browse_folder-seed-folder")
        listed = await call(
            "sharepoint_browse_folder",
            folder="sharepoint:///folders/b%21oB4UKtbhgJM1dlzaFrrvV8ZJTU3SVHXDiTDO4t3CSqTw9s5HDORSNLRDoZz1I_Q_/01UKPLM94OZ5K7N6WY9IBF1SMDTUQ8OPDR",
        )
        offers = _rows(listed, "items")
        for number, offer in enumerate(offers):
            _ = _serve_file(graph, f"offer {number}".encode(), handle=cast("str", offer["uri"]))

        read = [(await _read(cast("str", offer["uri"])))[1] for offer in offers]

        assert read == [f"offer {number}".encode() for number in range(len(offers))]

    async def test_a_file_that_names_another_file_leads_to_the_named_file(
        self, graph: respx.MockRouter
    ) -> None:
        plan, workbook = _hit("Brightway Launch Plan.docx"), _hit("Brightway Pricing.xlsx")
        _ = graph.post("/search/query").mock(
            side_effect=[
                httpx.Response(200, json=search_response([plan])),
                httpx.Response(200, json=search_response([workbook])),
            ]
        )
        plan_uri = cast(
            "str",
            _rows(await call("sharepoint_search_files", query="Launch Plan"), "files")[0]["uri"],
        )
        _ = _serve_file(graph, b"The budget is in Brightway Pricing.xlsx", handle=plan_uri)
        named = (await _read(plan_uri))[1].decode().removeprefix("The budget is in ")

        found = await call("sharepoint_search_files", query=named)
        workbook_uri = cast("str", _rows(found, "files")[0]["uri"])
        _ = _serve_file(graph, b"budget 120000", handle=workbook_uri)

        assert _names(found, "files") == [named]
        assert (await _read(workbook_uri))[1] == b"budget 120000"

    async def test_a_file_of_exactly_ten_megabytes_is_read_as_a_whole(
        self, graph: respx.MockRouter
    ) -> None:
        whole = b"x" * (10 * _MEGABYTE)
        _ = _serve_file(graph, whole)

        assert (await _read(_FILE))[1] == whole


class TestAFileThatCannotBeRead:
    async def test_a_folder_is_refused_with_the_handle_that_lists_it(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_item({"folder": {"childCount": 6}}, size=0))
        )
        content = graph.get(f"{_ITEM_PATH}/content")

        with pytest.raises(ToolError) as refused:
            _ = await _read(_FILE)

        assert "has no content to read" in str(refused.value)
        assert DriveFolderHandle("b!SYNTHETICDRIVE", _FILE_ID).uri in str(refused.value)
        assert not content.called

    @pytest.mark.parametrize(
        "facets",
        [{"package": {"type": "oneNote"}}, {"remoteItem": {"id": "01SYNTHETICREMOTE"}}],
        ids=["onenote-notebook", "shortcut-to-a-folder"],
    )
    async def test_an_item_that_only_looks_like_a_file_is_not_read(
        self, graph: respx.MockRouter, facets: Mapping[str, object]
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_item(facets)))
        content = graph.get(f"{_ITEM_PATH}/content")

        with pytest.raises(ToolError) as refused:
            _ = await _read(_FILE)

        assert "does not hold this item as a plain file" in str(refused.value)
        assert "Open this item in a browser" in str(refused.value)
        assert not content.called

    async def test_a_file_of_unknown_size_is_not_read(self, graph: respx.MockRouter) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_item(size=None)))
        content = graph.get(f"{_ITEM_PATH}/content")

        with pytest.raises(ToolError) as refused:
            _ = await _read(_FILE)

        assert "did not say how large this file is" in str(refused.value)
        assert "Open the file in a browser" in str(refused.value)
        assert not content.called

    async def test_a_file_that_arrives_empty_is_blamed_on_microsoft(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_item(size=2048)))
        _ = graph.get(f"{_ITEM_PATH}/content").mock(return_value=httpx.Response(200, content=b""))

        with pytest.raises(ToolError) as refused:
            _ = await _read(_FILE)

        assert "fault on Microsoft's side" in str(refused.value)
        assert "Ask for this file again later" in str(refused.value)
        assert "open the file in a browser" in str(refused.value)


class TestAFolderListThatIsNotComplete:
    async def test_a_folder_of_more_than_a_thousand_items_says_that_the_list_can_miss_files(
        self, graph: respx.MockRouter
    ) -> None:
        archive: list[Row] = [
            {
                "id": f"01FILE{number}",
                "name": f"File {number}",
                "lastModifiedDateTime": (_FIRST_EDIT + timedelta(minutes=number)).isoformat(),
            }
            for number in range(1500)
        ]
        _ = _serve_children(graph, *archive)

        level = await call("sharepoint_browse_folder", folder=_FOLDER, order_by="last_modified")

        names = [row["name"] for row in _rows(level, "items")]
        assert level["capped"] is True
        assert level["order_covers_level"] is False
        assert 0 < len(names) <= 50
        assert names[0] == "File 999"
        assert "File 1000" not in names

    async def test_a_list_that_microsoft_never_finishes_is_reported_on_both_tries(
        self, graph: respx.MockRouter
    ) -> None:
        more = f"https://graph.microsoft.com/v1.0/drives/{_DRIVE}/items/{_FOLDER_ID}/children?$skiptoken=1"
        _ = _serve_children(graph, next_link=more)

        with pytest.raises(ToolError) as first:
            _ = await call("sharepoint_browse_folder", folder=_FOLDER)
        with pytest.raises(ToolError) as second:
            _ = await call("sharepoint_browse_folder", folder=_FOLDER)

        for failed in (first, second):
            assert "would not finish sending this list" in str(failed.value)
            assert "stop and report it" in str(failed.value)


class TestWhatMicrosoftAnswersWhenAReadFails:
    async def test_one_busy_answer_is_waited_out(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        busy = httpx.Response(429, headers={"retry-after": "30"}, json=_BUSY)
        _ = graph.get(_ITEM_PATH).mock(side_effect=[busy, httpx.Response(200, json=_item(size=4))])
        _ = graph.get(f"{_ITEM_PATH}/content").mock(
            return_value=httpx.Response(200, content=b"14 J")
        )

        assert (await _read(_FILE))[1] == b"14 J"
        assert retry_sleeps.delays == [30]

    async def test_a_microsoft_that_stays_busy_is_reported_with_the_wait_it_asked_for(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(429, headers={"retry-after": "30"}, json=_BUSY)
        )

        with pytest.raises(ToolError) as busy:
            _ = await _read(_FILE)

        assert "asked to be left alone for 30 seconds" in str(busy.value)
        assert retry_sleeps.delays
        assert min(retry_sleeps.delays) >= 30

    async def test_a_read_that_fails_twice_is_reported_as_failed_and_not_to_be_repeated(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(500, json=_BUSY))

        with pytest.raises(ToolError) as first:
            _ = await _read(_FILE)
        with pytest.raises(ToolError) as second:
            _ = await _read(_FILE)

        assert "Retry once" in str(first.value)
        assert "stop and report it" in str(second.value)

    async def test_a_rejected_read_gives_the_reason_and_is_not_to_be_repeated(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(400, json=_REJECTED))

        with pytest.raises(ToolError) as rejected:
            _ = await _read(_FILE)

        assert "the item is not valid for this operation" in str(rejected.value)
        assert "will fail the same way" in str(rejected.value)

    async def test_a_missing_consent_is_explained_and_never_reaches_graph(
        self, graph: respx.MockRouter
    ) -> None:
        async def refuse(_self: AzureProvider, **_: object) -> object:
            raise ClientAuthenticationError("AADSTS65001: the administrator never consented")

        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            patch.setattr(AzureProvider, "get_obo_credential", refuse)
            async with Client(FastMCPTransport(_server()), mode="legacy") as client:
                with pytest.raises(ToolError) as refused:
                    _ = await client.call_tool("sharepoint_read_file", {"file": _FILE})

        assert "ask a Microsoft 365 administrator to grant" in str(refused.value)
        assert "sign in to this connector again" in str(refused.value)
        assert "does not exist" not in str(refused.value)
        assert not graph.calls


class TestWhereTheFilesAreStored:
    async def test_the_drive_of_the_user_is_named_with_its_web_address(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-sharepoint_list_drives-mine")

        listed = await call("sharepoint_list_drives")

        mine = _rows(listed, "drives")[0]
        assert (
            mine["web_url"]
            == "https://contoso-my.sharepoint.com/personal/mia_example_test/Documents"
        )
        assert str(mine["root_uri"]).startswith("sharepoint:///folders/")

    async def test_the_tool_has_no_site_to_list_and_says_it_lists_no_site_library(self) -> None:
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            tools = {tool.name: tool for tool in await client.list_tools()}

        listing = tools["sharepoint_list_drives"]
        assert listing.input_schema.get("properties", {}) == {}
        assert "does not list the document libraries of SharePoint sites" in (
            listing.description or ""
        )


class TestFindingASite:
    async def test_a_search_without_a_match_answers_with_an_empty_list(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/sites").mock(return_value=httpx.Response(200, json={"value": []}))

        found = await call("sharepoint_search_sites", query="Zephyr")

        assert (found["sites"], found["capped"]) == ([], False)

    async def test_a_search_with_more_matches_than_the_limit_says_that_it_stopped_early(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-sharepoint_search_sites-all")

        found = await call("sharepoint_search_sites", query="Project", limit=2)

        assert len(_rows(found, "sites")) == 2
        assert found["capped"] is True

    async def test_a_search_with_more_than_a_thousand_matches_stays_capped_at_the_highest_limit(
        self, graph: respx.MockRouter
    ) -> None:
        sites = [
            {
                "id": f"site{number}",
                "name": f"project{number}",
                "webUrl": f"https://x.invalid/{number}",
            }
            for number in range(1001)
        ]
        _ = graph.get("/sites").mock(return_value=httpx.Response(200, json={"value": sites}))

        found = await call("sharepoint_search_sites", query="Project", limit=1000)

        assert len(_rows(found, "sites")) == 1000
        assert found["capped"] is True
