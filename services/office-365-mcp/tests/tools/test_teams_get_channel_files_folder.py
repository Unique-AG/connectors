import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import DriveFolderHandle, drive_folder_handle
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import teams_get_channel_files_folder as getter

_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"
_FILES_FOLDER_PATH = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/filesFolder"

_DRIVE_ID = "b!SYNTHETICDRIVE0000"
_FOLDER_ID = "01SYNTHETICFOLDER0000"
_WEB_URL = "https://contoso.sharepoint.invalid/teams/engineering/Shared%20Documents/General"

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n\s*\n|\n\s*-\s+")


def _folder_payload(*, parent: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "id": _FOLDER_ID,
        "createdDateTime": "0001-01-01T00:00:00Z",
        "lastModifiedDateTime": "2020-01-23T18:47:13Z",
        "name": "General",
        "webUrl": _WEB_URL,
        "size": 2374080,
        "parentReference": {"driveId": _DRIVE_ID, "driveType": "documentLibrary"}
        if parent is None
        else parent,
        "folder": {"childCount": 7},
    }


def _sentences(text: str) -> list[str]:
    return [" ".join(part.split()) for part in _SENTENCE_BREAK.split(text) if part.strip()]


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    getter.register(mcp, transport)
    tool = await mcp.get_tool(getter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _property(parameters: Mapping[str, object], name: str) -> Mapping[str, object]:
    return cast(
        "Mapping[str, object]", cast("Mapping[str, object]", parameters["properties"])[name]
    )


@pytest.fixture
def files_folder(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_FILES_FOLDER_PATH).mock(
        return_value=httpx.Response(200, json=_folder_payload())
    )


class TestTheCallItMakes:
    async def test_it_reads_the_files_folder_of_the_channel_it_was_given(
        self, client: GraphServiceClient, files_folder: respx.Route
    ) -> None:
        _ = await getter.teams_get_channel_files_folder(
            client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
        )

        assert files_folder.call_count == 1

    async def test_it_sends_no_odata_query_because_graph_supports_none(
        self, client: GraphServiceClient, files_folder: respx.Route
    ) -> None:
        _ = await getter.teams_get_channel_files_folder(
            client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
        )

        assert files_folder.calls.last.request.url.query == b""

    def test_the_startup_probe_calls_this_tool_with_both_ids(self) -> None:
        assert set(getter.GRAPH_CALL_EXAMPLE) == {"team_id", "channel_id"}

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert getter.GRAPH_PERMISSIONS == ("Files.Read.All",)


class TestTheFolderItAnswers:
    @pytest.mark.usefixtures("files_folder")
    async def test_the_uri_is_a_folder_handle_that_sharepoint_browse_folder_parses(
        self, client: GraphServiceClient
    ) -> None:
        folder = await getter.teams_get_channel_files_folder(
            client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
        )

        assert folder.uri == DriveFolderHandle(_DRIVE_ID, _FOLDER_ID).uri
        assert drive_folder_handle(folder.uri) == DriveFolderHandle(_DRIVE_ID, _FOLDER_ID)

    @pytest.mark.usefixtures("files_folder")
    async def test_the_child_count_and_the_web_address_come_through(
        self, client: GraphServiceClient
    ) -> None:
        folder = await getter.teams_get_channel_files_folder(
            client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
        )

        assert folder.is_folder is True
        assert folder.child_count == 7
        assert folder.web_url == _WEB_URL
        assert folder.name == "General"
        assert folder.drive_type == "documentLibrary"

    @pytest.mark.usefixtures("files_folder")
    async def test_an_answer_with_no_parent_id_has_no_parent_uri(
        self, client: GraphServiceClient
    ) -> None:
        folder = await getter.teams_get_channel_files_folder(
            client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
        )

        assert folder.parent_uri is None

    @pytest.mark.usefixtures("files_folder")
    async def test_the_creation_time_of_year_one_that_microsoft_documents_still_parses(
        self, client: GraphServiceClient
    ) -> None:
        folder = await getter.teams_get_channel_files_folder(
            client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
        )

        assert folder.created_at == datetime(1, 1, 1, tzinfo=UTC)


class TestWhatItRefuses:
    async def test_an_answer_with_no_drive_id_is_refused_with_the_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_FILES_FOLDER_PATH).mock(
            return_value=httpx.Response(
                200, json=_folder_payload(parent={"driveType": "documentLibrary"})
            )
        )

        with pytest.raises(ToolError, match="without the drive id") as refused:
            _ = await getter.teams_get_channel_files_folder(
                client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
            )

        assert "cannot browse" in str(refused.value)

    async def test_an_answer_with_no_parent_reference_is_refused_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        payload = _folder_payload()
        del payload["parentReference"]
        graph.get(_FILES_FOLDER_PATH).mock(return_value=httpx.Response(200, json=payload))

        with pytest.raises(ToolError, match="without the drive id"):
            _ = await getter.teams_get_channel_files_folder(
                client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
            )


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_FILES_FOLDER_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await getter.teams_get_channel_files_folder(
                client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
            )

    async def test_a_404_arrives_classified_as_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_FILES_FOLDER_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await getter.teams_get_channel_files_folder(
                client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
            )


class TestHowItDeclaresItself:
    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is READ_ONLY["readOnlyHint"]
        assert annotations.open_world_hint is READ_ONLY["openWorldHint"]

    async def test_the_arguments_are_a_team_id_and_a_channel_id_and_both_are_required(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(cast("Mapping[str, object]", parameters["properties"])) == {
            "team_id",
            "channel_id",
        }
        assert set(cast("Sequence[str]", parameters["required"])) == {"team_id", "channel_id"}
        assert _property(parameters, "team_id")["minLength"] == 1
        assert _property(parameters, "channel_id")["minLength"] == 1

    async def test_each_id_description_runs_from_15_to_60_words_in_sentences_of_25_or_fewer(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        for name in ("team_id", "channel_id"):
            description = cast("str", _property(parameters, name)["description"])
            assert 15 <= len(description.split()) <= 60, name
            assert all(len(sentence.split()) <= 25 for sentence in _sentences(description)), name

    async def test_the_channel_id_description_does_not_send_the_model_to_a_search_tool(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        description = cast("str", _property(parameters, "channel_id")["description"])
        assert "exactly as teams_list_channels reported it" in description
        assert "teams_search_messages" not in description

    async def test_the_description_points_to_sharepoint_browse_folder_for_the_contents(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "The answer is the folder itself and not its contents." in description
        assert "pass the `uri` of the answer as `folder` to sharepoint_browse_folder" in description

    async def test_the_description_states_the_two_facts_that_microsoft_documents(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "For a private channel that Microsoft migrated, the answer is the root folder."
            in description
        )
        assert (
            "some special characters in a channel name make this call return an error"
            in description
        )

    async def test_the_description_is_a_lead_and_notes_in_short_sentences(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead, _break, notes = description.partition("\n\nNotes:\n")
        bullets = [line for line in notes.splitlines() if line.startswith("- ")]
        assert lead
        assert 1 <= len(bullets) <= 3
        assert 45 <= len(description.split()) <= 210
        assert all(len(sentence.split()) <= 25 for sentence in _sentences(description))
