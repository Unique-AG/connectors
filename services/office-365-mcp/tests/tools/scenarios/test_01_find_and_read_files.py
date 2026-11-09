import base64
import functools
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Never, cast

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


async def _resource(file: str, **arguments: object) -> TextResourceContents | BlobResourceContents:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            answer = await client.call_tool("sharepoint_read_file", {"file": file, **arguments})
    [block] = answer.content
    assert isinstance(block, EmbeddedResource)
    return block.resource


async def _read(file: str = _FILE, **arguments: object) -> tuple[str, bytes]:
    resource = await _resource(file, **arguments)
    if isinstance(resource, TextResourceContents):
        return resource.mime_type or "", resource.text.encode()
    assert isinstance(resource, BlobResourceContents)
    return resource.mime_type or "", base64.b64decode(resource.blob)


def _rows(answer: Mapping[str, object], key: str) -> list[Row]:
    return cast("list[Row]", answer[key])


def _names(answer: Mapping[str, object], key: str) -> list[object]:
    return [row["name"] for row in _rows(answer, key)]


def _row(answer: Mapping[str, object], key: str, field: str, value: str) -> Row:
    return next(row for row in _rows(answer, key) if row[field] == value)


async def _seed_files() -> Mapping[str, object]:
    top = await call("sharepoint_browse_folder", limit=100)
    seed = _row(top, "items", "name", "seed-v1 Seed Files")
    return await call("sharepoint_browse_folder", folder=seed["uri"], limit=100)


async def _seed_uri(name: str) -> str:
    return cast("str", _row(await _seed_files(), "items", "name", name)["uri"])


def _query_string(route: respx.Route) -> str:
    body = cast("Row", json.loads(route.calls.last.request.content))
    request = cast("list[Row]", body["requests"])[0]
    return cast("str", cast("Row", request["query"])["queryString"])


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
        route = serve(graph, "rec-tool-sharepoint_search_files-order")[("POST", "/search/query")]

        found = await call(
            "sharepoint_search_files", query="seed-v1 Order", sort_by="last_modified"
        )

        first = _rows(found, "files")[0]
        assert (first["name"], first["last_modified_by"]) == ("seed-v1 Order D.txt", "Anna Meier")
        assert _names(found, "files") == [f"seed-v1 Order {letter}.txt" for letter in "DCBA"]
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
        _ = serve(graph, "rec-tool-sharepoint_search_files-none")

        found = await call("sharepoint_search_files", query="seed-v1 zzqqxx nothing")

        assert (found["files"], found["next_offset"]) == ([], None)


class TestBrowsingAFolder:
    async def test_a_folder_lists_one_level_newest_first(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-sharepoint_browse_folder-newest-first")
        ordered = await _seed_uri("seed-v1 Ordered")

        level = await call("sharepoint_browse_folder", folder=ordered, order_by="last_modified")

        assert _names(level, "items") == [f"seed-v1 Order {letter}.txt" for letter in "CBA"]
        assert level["order_covers_level"] is True
        assert [route.call_count for route in routes.values()] == [1, 1, 1, 1]

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
        _ = serve(graph, "rec-tool-sharepoint_browse_folder-channel-files")
        teams = await call("teams_list_my_teams")
        team = cast("str", _row(teams, "teams", "display_name", "seed-v1 team")["team_id"])
        channels = await call("teams_list_channels", team_id=team, membership_type="standard")
        channel = _row(channels, "channels", "display_name", "seed-v1 Long channel")["channel_id"]
        folder = await call("teams_get_channel_files_folder", team_id=team, channel_id=channel)

        listed = await call("sharepoint_browse_folder", folder=folder["uri"], limit=100)

        assert _names(listed, "items") == ["seed-v1 Channel Notes.txt"]


_SHARING_LINK = (
    "https://contoso-my.sharepoint.com/personal/mia_example_test/Documents/"
    + "seed-v1%20Seed%20Files/seed-v1%20Project%20Plan.docx"
)


class TestReadingAFile:
    @pytest.mark.parametrize(
        ("mime_type", "fixture", "name", "size"),
        [
            (_PDF, "pdf", "seed-v1 Brochure Proof.pdf", 860),
            ("text/plain", "text-2000", "seed-v1 Text 2000.txt", 2000),
        ],
        ids=["pdf", "plain-text"],
    )
    async def test_a_file_that_needs_no_conversion_comes_back_as_it_is(
        self, graph: respx.MockRouter, mime_type: str, fixture: str, name: str, size: int
    ) -> None:
        routes = serve(graph, f"rec-tool-sharepoint_read_file-{fixture}")
        file = await _seed_uri(name)

        read_mime, content = await _read(file)

        assert (read_mime, len(content)) == (mime_type, size)
        [asked] = [route for (_, path), route in routes.items() if path.endswith("/content")]
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
        _ = serve(graph, "rec-tool-sharepoint_read_file-folder-each")
        reports = await call(
            "sharepoint_browse_folder",
            folder=await _seed_uri("seed-v1 Reports"),
            limit=100,
        )

        read = [
            (await _read(cast("str", _row(reports, "items", "name", name)["uri"])))[1]
            for name in ("seed-v1 Report A.txt", "seed-v1 Report B.txt", "seed-v1 Report C.docx")
        ]

        assert read[:2] == [
            b"Report A. Sales rose in the first quarter.\n",
            b"Report B. Costs stayed flat in the second quarter.\n",
        ]
        assert read[2][:2] == b"PK"

    async def test_a_file_that_names_another_file_leads_to_the_named_file(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-sharepoint_read_file-names-another")
        pointer = (await _read(await _seed_uri("seed-v1 Read me first.txt")))[1].decode()
        named = pointer.removeprefix("See ").removesuffix(" for the plan.\n")

        found = await call("sharepoint_search_files", query="seed-v1 Project Plan", limit=1)
        mime_type, content = await _read(cast("str", _rows(found, "files")[0]["uri"]))

        assert _names(found, "files") == [named]
        assert (mime_type, content[:2]) == (_DOCX, b"PK")

    async def test_a_file_of_exactly_ten_megabytes_is_read_as_a_whole(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-sharepoint_read_file-10mib")

        assert len((await _read(await _seed_uri("seed-v1 Scan 10MiB.bin")))[1]) == 10 * _MEGABYTE


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

    async def test_the_libraries_of_a_site_are_listed_from_its_web_address(
        self, graph: respx.MockRouter
    ) -> None:
        site = graph.get("/sites/contoso.sharepoint.com:/sites/Sales").mock(
            return_value=httpx.Response(200, json={"id": "contoso.sharepoint.com,s1,w1"})
        )
        libraries = graph.route(method="GET", path__regex=r"/sites/[^/]+/drives$").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "b!SALESLIBRARY",
                            "name": "Shared Documents",
                            "driveType": "documentLibrary",
                            "webUrl": "https://contoso.sharepoint.com/sites/Sales/Shared%20Documents",
                        }
                    ]
                },
            )
        )

        listed = await call(
            "sharepoint_list_drives", site="https://contoso.sharepoint.com/sites/Sales/"
        )

        [library] = _rows(listed, "drives")
        assert (library["name"], library["drive_type"]) == ("Shared Documents", "documentLibrary")
        assert str(library["root_uri"]).startswith("sharepoint:///folders/")
        assert (site.call_count, libraries.call_count, len(graph.calls)) == (1, 1, 2)

    async def test_the_library_of_a_recorded_team_site_is_listed(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-sharepoint_list_drives-site")

        listed = await call(
            "sharepoint_list_drives",
            site="https://contoso.sharepoint.com/teams/synthetic%20text%2001",
        )

        [library] = _rows(listed, "drives")
        assert library["drive_type"] == "documentLibrary"
        assert str(library["web_url"]).endswith("/Shared%20Documents")

    @pytest.mark.parametrize(
        "address",
        ["contoso.sharepoint.com/sites/Sales", "Sales", "https://contoso.sharepoint.com/%2e%2e/x"],
    )
    async def test_an_address_that_is_not_a_site_address_is_refused_before_any_request(
        self, graph: respx.MockRouter, address: str
    ) -> None:
        with pytest.raises(ToolError, match="takes the web address of a site"):
            _ = await call("sharepoint_list_drives", site=address)

        assert not graph.calls


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


class TestARequestThatCannotSucceed:
    @pytest.mark.parametrize(
        ("tool", "arguments", "told"),
        [
            ("sharepoint_read_file", {"file": _FOLDER}, "did not get a file handle"),
            ("sharepoint_browse_folder", {"folder": _FILE}, "takes a folder handle"),
        ],
        ids=["read-with-a-folder-handle", "browse-with-a-file-handle"],
    )
    async def test_a_handle_of_the_wrong_kind_is_refused_and_microsoft_is_not_asked(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: str
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call(tool, **cast("dict[str, Never]", arguments))

        assert told in str(refused.value)
        assert not graph.calls

    async def test_a_window_that_runs_backwards_is_refused(self, graph: respx.MockRouter) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_search_files",
                query="Brightway",
                modified_after="2026-10-30",
                modified_before="2026-10-26",
            )

        assert "`modified_before` falls before `modified_after`" in str(refused.value)
        assert not graph.calls

    async def test_a_search_with_no_word_in_it_is_refused(self, graph: respx.MockRouter) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call("sharepoint_search_files", query="   ")

        assert "holds no word to look for" in str(refused.value)
        assert not graph.calls

    @pytest.mark.parametrize(
        "value",
        ["Plan.docx", "http://contoso.sharepoint.invalid/Plan.docx", "https://["],
        ids=["name", "http", "broken-host"],
    )
    async def test_an_address_that_is_not_a_web_address_is_refused(
        self, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call("sharepoint_resolve_url", url=value)

        assert "did not get a web address" in str(refused.value)
        assert not graph.calls


class TestAFileInTheFormThatMiaNeeds:
    @pytest.mark.parametrize(
        ("name", "uri"),
        [
            ("Plan.docx", "file:///Plan.pdf"),
            ("Plan", "file:///Plan.pdf"),
            ("Plan.v2.docx", "file:///Plan.v2.pdf"),
            (None, "file:///resource.pdf"),
        ],
        ids=["extension", "no-extension", "two-dots", "no-name"],
    )
    async def test_a_converted_file_comes_back_as_a_pdf_with_a_pdf_name(
        self, graph: respx.MockRouter, name: str | None, uri: str
    ) -> None:
        body = {
            key: value for key, value in _item(size=7, mime_type=_DOCX).items() if key != "name"
        }
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=body | ({} if name is None else {"name": name}))
        )
        content = graph.get(f"{_ITEM_PATH}/content").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.")
        )

        resource = await _resource(_FILE, convert_to="pdf")

        assert (str(resource.uri), resource.mime_type) == (uri, _PDF)
        assert "format=pdf" in str(content.calls.last.request.url)

    @pytest.mark.parametrize(
        ("facet", "content"),
        [({"file": {}}, b"abc"), ({"file": {"mimeType": "text/plain"}}, b"caf\xe9")],
        ids=["no-type", "text-that-is-not-valid"],
    )
    async def test_a_file_with_no_usable_type_is_read_as_plain_bytes(
        self, graph: respx.MockRouter, facet: Row, content: bytes
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_item(facet, size=len(content)))
        )
        _ = graph.get(f"{_ITEM_PATH}/content").mock(
            return_value=httpx.Response(200, content=content)
        )

        assert await _read(_FILE) == ("application/octet-stream", content)

    async def test_a_file_larger_than_microsoft_said_is_refused_while_it_comes_in(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_item(size=4)))
        _ = graph.get(f"{_ITEM_PATH}/content").mock(
            return_value=httpx.Response(200, content=b"x" * (10 * _MEGABYTE + 1))
        )

        with pytest.raises(ToolError) as refused:
            _ = await _read(_FILE)

        assert "more than 10.0 MB" in str(refused.value)
        assert "https://contoso.sharepoint.invalid/sites/Sales/Brightway.pdf" in str(refused.value)


class TestAFolderInTheOrderThatMiaAsksFor:
    async def test_a_folder_is_listed_in_the_order_of_the_names(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-sharepoint_browse_folder-newest-first")
        ordered = await _seed_uri("seed-v1 Ordered")

        level = await call("sharepoint_browse_folder", folder=ordered, order_by="name")

        assert _names(level, "items") == [f"seed-v1 Order {letter}.txt" for letter in "ABC"]


def _search_answer(*containers: Row) -> Row:
    return {"value": [{"hitsContainers": list(containers)}]}


class TestWhatTheSearchAndTheListingsShow:
    async def test_a_search_on_a_site_names_the_site(self, graph: respx.MockRouter) -> None:
        sales = "https://contoso.sharepoint.invalid/sites/Sales"
        mine = "https://contoso-my.sharepoint.invalid/personal/mia"
        grouped = _search_answer(
            {
                "hits": [],
                "total": 0,
                "moreResultsAvailable": False,
                "aggregations": [
                    {
                        "field": "SPSiteURL",
                        "buckets": [
                            {"key": sales, "count": 3},
                            {"key": mine, "count": 1},
                            {"key": None, "count": 2},
                        ],
                    }
                ],
            }
        )
        _ = graph.post("/search/query").mock(return_value=httpx.Response(200, json=grouped))

        found = await call("sharepoint_search_files", query="Team Charter")

        assert _rows(found, "sites") == [
            {"web_url": sales, "match_count": 3},
            {"web_url": mine, "match_count": 1},
        ]

    @pytest.mark.parametrize(
        "answer",
        [
            _search_answer(),
            _search_answer(
                {
                    "hits": [],
                    "total": 0,
                    "moreResultsAvailable": False,
                    "aggregations": [
                        {"field": "FileType", "buckets": [{"key": "docx", "count": 3}]}
                    ],
                }
            ),
        ],
        ids=["no-group", "group-of-another-kind"],
    )
    async def test_a_search_answer_with_no_site_list_shows_no_site(
        self, graph: respx.MockRouter, answer: Row
    ) -> None:
        _ = graph.post("/search/query").mock(return_value=httpx.Response(200, json=answer))

        found = await call("sharepoint_search_files", query="Brightway")

        assert (found["files"], found["sites"]) == ([], [])

    async def test_a_time_window_with_exact_times_is_searched_to_the_moment(
        self, graph: respx.MockRouter
    ) -> None:
        route = serve(graph, "rec-tool-sharepoint_search_files-plan")[("POST", "/search/query")]

        _ = await call(
            "sharepoint_search_files",
            query="Brightway",
            modified_after="2026-10-26T08:00:00+00:00",
            modified_before="2026-10-30T17:45:30.250000+00:00",
        )

        asked = _query_string(route)
        assert "LastModifiedTime>=2026-10-26T08:00:00Z" in asked
        assert "LastModifiedTime<=2026-10-30T17:45:30.250000Z" in asked

    @pytest.mark.parametrize(
        ("tool", "path", "rows", "key"),
        [
            (
                "sharepoint_list_drives",
                "/me/drives",
                [{"id": "b!SYNTHETICDRIVE", "name": "OneDrive"}, {"name": "No id"}],
                "drives",
            ),
            (
                "sharepoint_search_sites",
                "/sites",
                [
                    {"id": "s1", "displayName": "Sales", "webUrl": "https://x.invalid/sales"},
                    {"id": "s2", "displayName": "No address"},
                ],
                "sites",
            ),
        ],
        ids=["drive-without-id", "site-without-address"],
    )
    async def test_an_entry_without_an_id_or_an_address_is_left_out(
        self, graph: respx.MockRouter, tool: str, path: str, rows: list[Row], key: str
    ) -> None:
        _ = graph.get(path).mock(return_value=httpx.Response(200, json={"value": rows}))
        arguments: Row = {"query": "Sales"} if key == "sites" else {}

        listed = await call(tool, **cast("dict[str, Never]", arguments))

        assert len(_rows(listed, key)) == 1
