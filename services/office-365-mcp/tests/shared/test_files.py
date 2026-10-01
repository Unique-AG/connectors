from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import cast

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphNotFound, graph_step
from office_365_mcp.shared import files
from office_365_mcp.shared.files import (
    STEP_DRIVE_ITEM,
    AttachableFile,
    attachable_files,
    attachment_handles,
)
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle

_DRIVE_ID = "b!SYNTHETICDRIVE0000"
_ITEM_ID = "01SYNTHETICFILE0000"
_OTHER_ITEM_ID = "01SYNTHETICFILE0001"

_FILE = DriveFileHandle(_DRIVE_ID, _ITEM_ID)
_OTHER_FILE = DriveFileHandle(_DRIVE_ID, _OTHER_ITEM_ID)

_ITEM_PATH = "/drives/b%21SYNTHETICDRIVE0000/items/01SYNTHETICFILE0000"
_OTHER_ITEM_PATH = "/drives/b%21SYNTHETICDRIVE0000/items/01SYNTHETICFILE0001"

_ETAG = '"{153FA47D-18C9-4179-BE08-9879815A9F90},2"'
_ATTACHMENT_ID = "153fa47d-18c9-4179-be08-9879815a9f90"
_WEB_DAV_URL = "https://contoso.sharepoint.invalid/sites/finance/Shared%20Documents/Budget.docx"
_NAME = "Budget.docx"


def _item(
    *,
    item_id: str = _ITEM_ID,
    name: str = _NAME,
    e_tag: str = _ETAG,
    drive_type: str = "documentLibrary",
    facet: str = "file",
) -> dict[str, object]:
    facets: dict[str, dict[str, object]] = {
        "file": {"file": {"mimeType": "application/octet-stream"}},
        "folder": {"folder": {"childCount": 3}},
        "package": {"package": {"type": "oneNote"}},
    }
    return {
        "id": item_id,
        "name": name,
        "eTag": e_tag,
        "webDavUrl": _WEB_DAV_URL,
        "parentReference": {"driveId": _DRIVE_ID, "driveType": drive_type},
        **facets[facet],
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object]) -> respx.Route:
    return graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=payload))


class TestAttachmentHandles:
    def test_file_handles_parse_in_the_order_given(self) -> None:
        assert attachment_handles([_FILE.uri, _OTHER_FILE.uri]) == (_FILE, _OTHER_FILE)

    def test_no_handle_parses_to_nothing(self) -> None:
        assert attachment_handles([]) == ()

    @pytest.mark.parametrize(
        "uri",
        [
            DriveFolderHandle(_DRIVE_ID, _ITEM_ID).uri,
            "https://contoso.sharepoint.invalid/sites/finance/Shared%20Documents/Budget.docx",
            "Budget.docx",
            _ITEM_ID,
            "",
        ],
    )
    def test_a_value_that_is_not_a_file_handle_is_refused_by_name(self, uri: str) -> None:
        refused = attachment_handles([_FILE.uri, uri])

        assert isinstance(refused, str)
        assert f"The attachment {uri!r} is not a file handle." in refused
        assert "sharepoint:///files/{drive_id}/{item_id}" in refused
        assert refused.endswith(
            "If you call this tool again with the same arguments, the call will fail the same way."
        )


class TestAttachableFiles:
    async def test_a_file_becomes_an_attachment_with_the_guid_of_its_etag(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item())

        found = await attachable_files(client, [_FILE])

        assert found == (
            AttachableFile(attachment_id=_ATTACHMENT_ID, web_dav_url=_WEB_DAV_URL, name=_NAME),
        )

    @pytest.mark.parametrize(
        "e_tag",
        [
            '"{153FA47D-18C9-4179-BE08-9879815A9F90},2"',
            '"{153fa47d-18c9-4179-be08-9879815a9f90},17"',
            "{153FA47D-18C9-4179-BE08-9879815A9F90},1",
        ],
    )
    async def test_the_attachment_id_is_the_guid_inside_the_etag_in_lowercase(
        self, client: GraphServiceClient, graph: respx.MockRouter, e_tag: str
    ) -> None:
        _ = _reads(graph, _item(e_tag=e_tag))

        found = await attachable_files(client, [_FILE])

        assert not isinstance(found, str)
        assert [file.attachment_id for file in found] == [_ATTACHMENT_ID]

    async def test_the_read_selects_the_webdav_address_by_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _item())

        _ = await attachable_files(client, [_FILE])

        selected = read.calls.last.request.url.params["$select"].split(",")
        assert set(selected) == {
            "id",
            "name",
            "eTag",
            "webDavUrl",
            "file",
            "folder",
            "parentReference",
        }

    async def test_it_reads_each_file_once_and_in_order(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        first = _reads(graph, _item())
        second = graph.get(_OTHER_ITEM_PATH).mock(
            return_value=httpx.Response(
                200,
                json=_item(
                    item_id=_OTHER_ITEM_ID,
                    name="Plan.pptx",
                    e_tag='"{0A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D},1"',
                ),
            )
        )

        found = await attachable_files(client, [_FILE, _OTHER_FILE])

        assert not isinstance(found, str)
        assert [file.name for file in found] == [_NAME, "Plan.pptx"]
        assert (first.call_count, second.call_count) == (1, 1)
        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.url.raw_path.decode().split("?")[0] for call in made] == [
            f"/v1.0{_ITEM_PATH}",
            f"/v1.0{_OTHER_ITEM_PATH}",
        ]

    async def test_no_handle_reads_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        assert await attachable_files(client, []) == ()
        assert len(graph.calls) == 0

    async def test_each_read_is_measured_as_one_drive_item_step(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _ = _reads(graph, _item())
        _ = graph.get(_OTHER_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_item(item_id=_OTHER_ITEM_ID))
        )
        measured: list[str] = []

        def recording(step: str) -> AbstractContextManager[None]:
            measured.append(step)
            return graph_step(step)

        monkeypatch.setattr(files, "graph_step", recording)

        _ = await attachable_files(client, [_FILE, _OTHER_FILE])

        assert measured == [STEP_DRIVE_ITEM, STEP_DRIVE_ITEM]

    def test_its_step_is_the_drive_item_read(self) -> None:
        assert STEP_DRIVE_ITEM == "drive_item"


class TestWhatItRefusesToAttach:
    async def test_a_folder_is_refused_with_its_folder_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item(facet="folder"))

        refused = await attachable_files(client, [_FILE])

        assert isinstance(refused, str)
        assert "names a folder, and this tool attaches files only" in refused
        assert DriveFolderHandle(_DRIVE_ID, _ITEM_ID).uri in refused
        assert "sharepoint_browse_folder" in refused

    async def test_an_item_that_is_not_a_plain_file_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item(facet="package"))

        refused = await attachable_files(client, [_FILE])

        assert isinstance(refused, str)
        assert "is not a plain file in Microsoft 365" in refused

    async def test_a_file_in_a_personal_onedrive_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item(drive_type="personal"))

        refused = await attachable_files(client, [_FILE])

        assert isinstance(refused, str)
        assert f"The attachment {_FILE.uri} is in a personal OneDrive." in refused
        assert "only when the file is already in SharePoint" in refused

    @pytest.mark.parametrize("drive_type", ["business", "documentLibrary"])
    async def test_a_file_in_a_work_drive_or_a_library_is_attached(
        self, client: GraphServiceClient, graph: respx.MockRouter, drive_type: str
    ) -> None:
        _ = _reads(graph, _item(drive_type=drive_type))

        found = await attachable_files(client, [_FILE])

        assert not isinstance(found, str)

    @pytest.mark.parametrize(
        "missing",
        [
            {"eTag": None},
            {"eTag": '"153FA47D-18C9-4179-BE08-9879815A9F90,2"'},
            {"eTag": '"{not-a-guid},2"'},
            {"webDavUrl": None},
            {"name": None},
        ],
        ids=["no-etag", "etag-without-braces", "etag-without-guid", "no-webdav", "no-name"],
    )
    async def test_a_file_without_a_detail_teams_needs_is_refused(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        missing: dict[str, str | None],
    ) -> None:
        _ = _reads(graph, {**_item(), **missing})

        refused = await attachable_files(client, [_FILE])

        assert isinstance(refused, str)
        assert f"Microsoft 365 did not send all the details of the attachment {_FILE.uri}." in (
            refused
        )
        assert "Tell the user to attach the file in Microsoft Teams instead." in refused

    async def test_a_refusal_stops_the_reads_that_come_after_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item(facet="folder"))
        after = graph.get(_OTHER_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_item(item_id=_OTHER_ITEM_ID))
        )

        refused = await attachable_files(client, [_FILE, _OTHER_FILE])

        assert isinstance(refused, str)
        assert after.call_count == 0

    async def test_a_file_graph_does_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Item not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await attachable_files(client, [_FILE])
