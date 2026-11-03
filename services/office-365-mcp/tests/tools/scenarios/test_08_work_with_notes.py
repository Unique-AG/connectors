import base64
import functools
import json
import re
from collections.abc import Mapping, Sequence
from html import unescape
from typing import Never, cast
from urllib.parse import unquote

import httpx
import pytest
import respx
from azure.core.exceptions import ClientAuthenticationError
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from mcp.types import BlobResourceContents, EmbeddedResource
from respx.models import Call

from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteOperationHandle,
    OnenoteOwner,
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from tests.conftest import RecordedSleeps
from tests.e2e.test_scenarios import build_server, patch_obo
from tests.tools.scenarios.support import Person, call, serve

type Row = dict[str, object]
type Failure = httpx.Response | Exception
type Routes = dict[tuple[str, str], respx.Route]

_PAGE_ID = "1-SYNTHETICPAGE00000000000000000000!ABCDEF"
_SECTION_ID = "1-SYNTHETICSECTION0000!ABCDEF"
_NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0000!ABCDEF"
_GROUP_ID = "5c6b7a81-2f0d-4a24-9b1e-8a9c3c470f9e"
_SEED_TEAM_ID = "00000000-e7a0-41c6-863d-0548ee2dacdd"
_TEAM = OnenoteOwner("groups", _GROUP_ID)
_PAGE = OnenotePageHandle(_PAGE_ID).uri
_TEAM_PAGE = OnenotePageHandle(_PAGE_ID, owner=_TEAM).uri
_SECTION = OnenoteSectionHandle(_SECTION_ID).uri
_TEAM_SECTION = OnenoteSectionHandle(_SECTION_ID, owner=_TEAM).uri
_NOTEBOOK = OnenoteNotebookHandle(_NOTEBOOK_ID).uri
_TEAM_NOTEBOOK = OnenoteNotebookHandle(_NOTEBOOK_ID, owner=_TEAM).uri
_PAGE_PATH = f"/me/onenote/pages/{_PAGE_ID}"
_TEAM_PAGE_PATH = f"/groups/{_GROUP_ID}/onenote/pages/{_PAGE_ID}"
_WEB_URL = "https://onenote.example.invalid/pages/acme-kickoff"
_BUSY = {"error": {"code": "activityLimitReached", "message": "busy"}}
_MEGABYTE = 1024 * 1024
_SITE = OnenoteOwner(
    "sites",
    "contoso.sharepoint.invalid,0d1e2f3a-0000-4000-8000-000000000001,4b5c6d7e-0000-4000-8000-000000000002",
)
_SITE_NOTEBOOK = OnenoteNotebookHandle(_NOTEBOOK_ID, owner=_SITE).uri
_SITE_SECTION = OnenoteSectionHandle(_SECTION_ID, owner=_SITE).uri
_SITE_PAGE = OnenotePageHandle(_PAGE_ID, owner=_SITE).uri
_OPERATION_ID = "1-SYNTHETICOPERATION0000!0-ABCDEF"
_COPIES_SECTION = "3-00000000-eb48-4d62-8279-36b65ea83422"
_PICTURE = "https://graph.microsoft.com/v1.0/users('synthetic')/onenote/resources/RES1/$value"
_SITE_REFUSED = "documents no copy from or into a notebook of a SharePoint site"


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


def _sent(graph: respx.MockRouter) -> list[tuple[str, str]]:
    return [(c.request.method, c.request.url.path) for c in cast("Sequence[Call]", graph.calls)]


async def _call(tool: str, arguments: Row, *, person: Person | None = None) -> Mapping[str, object]:
    return await call(tool, person=person, **cast("dict[str, Never]", arguments))


async def _bytes_of(tool: str, **arguments: object) -> bytes:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            answer = await client.call_tool(tool, arguments)
    [block] = answer.content
    assert isinstance(block, EmbeddedResource)
    assert isinstance(block.resource, BlobResourceContents)
    return base64.b64decode(block.resource.blob)


def _rows(answer: Mapping[str, object], key: str) -> list[Row]:
    return cast("list[Row]", answer[key])


def _page(title: str = "Acme kickoff", *, page_id: str = _PAGE_ID) -> Row:
    return {
        "id": page_id,
        "title": title,
        "createdDateTime": "2026-03-01T09:00:00Z",
        "lastModifiedDateTime": "2026-03-04T10:30:00Z",
        "links": {"oneNoteWebUrl": {"href": _WEB_URL}, "oneNoteClientUrl": None},
        "parentSection": {"id": _SECTION_ID, "displayName": "Work"},
        "parentNotebook": {"id": _NOTEBOOK_ID, "displayName": "Customers"},
    }


def _notebook(*, shared: bool = False) -> Row:
    return {
        "id": _NOTEBOOK_ID,
        "displayName": "Customers",
        "isShared": shared,
        "userRole": "Owner",
    }


def _section() -> Row:
    return {
        "id": _SECTION_ID,
        "displayName": "Work",
        "parentNotebook": {"id": _NOTEBOOK_ID, "displayName": "Customers"},
    }


def _own_notes(graph: respx.MockRouter) -> None:
    _ = graph.get(_PAGE_PATH).mock(return_value=httpx.Response(200, json=_page()))
    _ = graph.get(f"/me/onenote/notebooks/{_NOTEBOOK_ID}").mock(
        return_value=httpx.Response(200, json=_notebook())
    )
    _ = graph.get(f"/me/onenote/sections/{_SECTION_ID}").mock(
        return_value=httpx.Response(200, json=_section())
    )


def _page_html(content: bytes = b"<html><body><p>decision one</p></body></html>") -> httpx.Response:
    return httpx.Response(200, content=content, headers={"content-type": "text/html"})


def _id_in(routes: Routes, method: str, marker: str, *, whole: bool = False) -> str:
    [only] = {
        path.split(marker, 1)[1].split("/", 1)[0]
        for (verb, path) in routes
        if verb == method and marker in path and not (whole and "/" in path.split(marker, 1)[1])
    }
    return only


async def _gallery_page() -> str:
    notebooks = await call("onenote_list_notebooks", name_contains="seed-v1 Dogfood")
    sections = await call(
        "onenote_list_sections",
        parent=_rows(notebooks, "notebooks")[0]["uri"],
        name_contains="Reading",
    )
    pages = await call(
        "onenote_list_pages",
        section=_rows(sections, "sections")[0]["uri"],
        title_contains="Gallery",
    )
    return cast("str", _rows(pages, "pages")[0]["uri"])


class TestFindingNotes:
    async def test_a_page_is_found_by_a_word_in_its_title(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-onenote_list_pages-title")
        section = OnenoteSectionHandle(_id_in(routes, "GET", "/me/onenote/sections/")).uri

        found = await call("onenote_list_pages", section=section, title_contains="synthetic")

        [only] = _rows(found, "pages")
        assert only["title"] == "synthetic text 19"
        listing = [route for (_, path), route in routes.items() if path.endswith("/pages")][0]
        assert (
            "contains(tolower(title),'synthetic')"
            in listing.calls.last.request.url.params["$filter"]
        )

    async def test_a_new_page_with_an_empty_title_is_found_by_the_time_it_was_created(
        self, graph: respx.MockRouter
    ) -> None:
        fresh = _page("") | {"createdDateTime": "2026-10-30T09:59:00Z"}

        def pages(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"value": [] if "$filter" in request.url.params else [fresh]}
            )

        listing = graph.get("/me/onenote/pages").mock(side_effect=pages)

        by_title = await call("onenote_list_pages", title_contains="Weekly sync")
        by_time = await call("onenote_list_pages", order_by="created_desc")

        assert _rows(by_title, "pages") == []
        [only] = _rows(by_time, "pages")
        assert only["title"] == "" and only["created_at"] == "2026-10-30T09:59:00Z"
        assert listing.calls.last.request.url.params["$orderby"] == "createdDateTime desc"

    async def test_a_search_by_a_word_of_the_body_is_not_offered(self) -> None:
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            tools = {tool.name: tool for tool in await client.list_tools()}

        listing = tools["onenote_list_pages"]
        asked = set(cast("Mapping[str, object]", listing.input_schema["properties"]))
        assert not asked & {"query", "text", "body", "body_contains", "content_contains"}
        assert "matches the title only" in (listing.description or "")

    async def test_a_notebook_from_a_web_address_gives_its_sections(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-onenote_find_notebook_from_url-seed")
        listing = serve(graph, "rec-tool-onenote_list_sections-notebook")

        notebook = await call(
            "onenote_find_notebook_from_url",
            web_url="https://contoso-my.sharepoint.com/personal/mia_example_test/Documents/synthetic%20text%2001",
        )
        notebook_id = _id_in(listing, "GET", "/me/onenote/notebooks/")
        sections = await call(
            "onenote_list_sections", parent=OnenoteNotebookHandle(notebook_id).uri
        )

        assert (notebook["name"], str(notebook["uri"]).endswith(notebook_id)) == (
            "seed-v1 Dogfood Notes",
            True,
        )
        assert [row["name"] for row in _rows(sections, "sections")] == [
            "seed-v1 Planning",
            "seed-v1 Reading",
        ]

    async def test_notebooks_with_a_word_in_the_name_come_with_their_sections(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-onenote_list_notebooks-seed")

        listed = await call("onenote_list_notebooks", name_contains="dogfood")

        [only] = _rows(listed, "notebooks")
        assert only["name"] == "seed-v1 Dogfood Notes"
        assert {"seed-v1 Planning", "seed-v1 Reading"} <= {
            row["name"] for row in cast("list[Row]", only["sections"])
        }
        first = routes[("GET", "/me/onenote/notebooks")]
        assert "dogfood" in first.calls.last.request.url.params["$filter"]

    async def test_the_notebooks_opened_lately_come_in_the_order_microsoft_gives(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-onenote_list_recent_notebooks-recent")

        recent = await call("onenote_list_recent_notebooks")

        names = [row["name"] for row in _rows(recent, "notebooks")]
        assert names[-3:] == ["seed-v1 Spare", "seed-v1 Scratch", "seed-v1 Dogfood Notes"]
        opened = [cast("str", row["last_accessed_at"]) for row in _rows(recent, "notebooks")]
        assert opened == sorted(opened, reverse=True)


class TestReadingAPage:
    async def test_a_page_is_read_with_the_notes_it_holds(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-onenote_read_page-gallery")

        read = await call("onenote_read_page", page=await _gallery_page())

        assert [key for key, route in routes.items() if not route.called] == []
        assert "This page holds one picture." in cast("str", read["html"])
        assert cast("Row", read["page"])["title"] == "seed-v1 Gallery"

    async def test_a_page_of_exactly_one_megabyte_is_read_as_a_whole(
        self, graph: respx.MockRouter
    ) -> None:
        whole = b"<html><body>" + b"x" * (_MEGABYTE - 26) + b"</body></html>"
        assert len(whole) == _MEGABYTE
        _ = graph.get(_PAGE_PATH).mock(return_value=httpx.Response(200, json=_page()))
        _ = graph.get(f"{_PAGE_PATH}/content").mock(return_value=_page_html(whole))

        read = await call("onenote_read_page", page=_PAGE)

        assert len(cast("str", read["html"])) == _MEGABYTE


class TestCapturingNotes:
    async def test_three_notes_become_a_page_in_the_section_in_order(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-onenote_create_page-seed")
        section = OnenoteSectionHandle(_id_in(routes, "POST", "/me/onenote/sections/")).uri
        person = Person()

        created = await call(
            "onenote_create_page",
            title="Weekly sync",
            body_html="<p>first note</p><p>second note</p><p>third note</p>",
            section=section,
            person=person,
        )

        sent = [route for (verb, _), route in routes.items() if verb == "POST"][0]
        written = sent.calls.last.request.content.decode()
        assert (
            written.index("first note") < written.index("second note") < written.index("third note")
        )
        assert (created["section_uri"], person.asked) == (section, [])

    async def test_a_task_list_is_appended_and_nothing_else_is_sent(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-onenote_append_to_page-seed")
        page = OnenotePageHandle(_id_in(routes, "GET", "/me/onenote/pages/")).uri

        _ = await call("onenote_append_to_page", page=page, body_html='<p data-tag="to-do">buy</p>')

        [patch] = [
            route for (_, path), route in routes.items() if path.endswith("onenotePatchContent")
        ]
        commands = cast("list[Row]", json.loads(patch.calls.last.request.content)["commands"])
        assert [command["action"] for command in commands] == ["Append"]

    async def test_a_notebook_with_sections_and_a_section_group_is_set_up_without_a_question(
        self, graph: respx.MockRouter
    ) -> None:
        person = Person()
        _ = serve(graph, "rec-tool-onenote_create_notebook-new")
        notebook = await call("onenote_create_notebook", name="Project Falcon", person=person)
        graph.routes.clear()
        sections = serve(graph, "rec-tool-onenote_create_section-new")
        parent = OnenoteNotebookHandle(_id_in(sections, "POST", "/me/onenote/notebooks/")).uri
        plan = await call("onenote_create_section", parent=parent, name="Plan", person=person)
        graph.routes.clear()
        groups = serve(graph, "rec-tool-onenote_create_section_group-new")
        parent = OnenoteNotebookHandle(_id_in(groups, "POST", "/me/onenote/notebooks/")).uri
        archive = await call(
            "onenote_create_section_group", parent=parent, name="Archive", person=person
        )

        assert str(notebook["uri"]).startswith("onenote:///notebooks/")
        assert str(plan["uri"]).startswith("onenote:///sections/")
        assert str(archive["uri"]).startswith("onenote:///sectiongroups/")
        assert person.asked == []


class TestChangingANote:
    async def test_a_sentence_is_replaced_after_the_person_approves_and_nothing_else_is_sent(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-onenote_edit_page-replace-sentence")
        page = OnenotePageHandle(_id_in(routes, "POST", "/me/onenote/pages/")).uri
        person = Person()

        read = await call("onenote_read_page", page=page, include_ids=True)
        target = cast(
            "re.Match[str]", re.search(r'id="([^"]+)"[^>]*>First', cast("str", read["html"]))
        )[1]
        _ = await call(
            "onenote_edit_page",
            page=page,
            commands=[
                {
                    "target": target,
                    "action": "replace",
                    "content": '<p data-id="one">Changed sentence.</p>',
                }
            ],
            person=person,
        )

        [patch] = [
            route for (_, path), route in routes.items() if path.endswith("onenotePatchContent")
        ]
        [command] = cast("list[Row]", json.loads(patch.calls.last.request.content)["commands"])
        assert (command["action"], command["target"]) == ("Replace", target)
        assert "Changed sentence" in cast("str", command["content"])
        assert len(person.asked) == 1
        assert "A replace cannot be undone" in person.asked[0]

    async def test_a_page_is_erased_only_after_the_person_approves(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-onenote_delete_page-seed")
        page = OnenotePageHandle(_id_in(routes, "DELETE", "/me/onenote/pages/")).uri
        person = Person()

        erased = await call("onenote_delete_page", page=page, person=person)

        assert erased["deleted"] is True
        assert len(person.asked) == 1
        assert "no recycle bin" in person.asked[0]

    async def test_a_page_is_added_to_the_notebook_of_a_team_after_the_person_approves(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-onenote_create_page-team-section")
        team = OnenoteOwner("groups", _id_in(routes, "POST", "/groups/"))
        section = OnenoteSectionHandle(_id_in(routes, "POST", "/onenote/sections/"), owner=team).uri
        person = Person()

        created = await call(
            "onenote_create_page",
            title="Retro",
            body_html="<p>notes</p>",
            section=section,
            person=person,
        )

        assert str(created["uri"]).startswith(f"onenote:///groups/{team.owner_id}/pages/")
        assert len(person.asked) == 1
        assert "belongs to a Microsoft 365 group" in person.asked[0]


class TestAReadThatFails:
    @pytest.mark.parametrize(
        ("status", "told"),
        [
            (401, "Ask the user to sign in to this connector again"),
            (403, "grant the delegated permission Notes.Read"),
            (404, "Find it again with onenote_list_pages"),
        ],
        ids=["sign-in-expired", "no-access", "gone"],
    )
    async def test_a_page_that_microsoft_will_not_give_is_explained(
        self, graph: respx.MockRouter, status: int, told: str
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(return_value=httpx.Response(status, json=_BUSY))

        with pytest.raises(ToolError) as refused:
            _ = await call("onenote_read_page", page=_PAGE)

        assert told in str(refused.value)

    async def test_a_microsoft_that_stays_busy_is_reported_with_the_wait_it_asked_for(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(
            return_value=httpx.Response(429, headers={"retry-after": "30"}, json=_BUSY)
        )

        with pytest.raises(ToolError) as busy:
            _ = await call("onenote_read_page", page=_PAGE)

        assert "asked to be left alone for 30 seconds" in str(busy.value)
        assert retry_sleeps.delays
        assert min(retry_sleeps.delays) >= 30

    async def test_one_busy_answer_is_waited_out(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        busy = httpx.Response(429, headers={"retry-after": "30"}, json=_BUSY)
        _ = graph.get(_PAGE_PATH).mock(side_effect=[busy, httpx.Response(200, json=_page())])
        _ = graph.get(f"{_PAGE_PATH}/content").mock(return_value=_page_html())

        read = await call("onenote_read_page", page=_PAGE)

        assert "decision one" in cast("str", read["html"])
        assert retry_sleeps.delays == [30]

    @pytest.mark.parametrize(
        "failure",
        [httpx.Response(500, json=_BUSY), httpx.ReadTimeout("injected")],
        ids=["internal-error", "no-answer"],
    )
    async def test_a_read_that_fails_once_is_asked_again_and_gives_the_page(
        self, graph: respx.MockRouter, failure: Failure
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(side_effect=[failure, httpx.Response(200, json=_page())])
        _ = graph.get(f"{_PAGE_PATH}/content").mock(return_value=_page_html())

        with pytest.raises(ToolError) as first:
            _ = await call("onenote_read_page", page=_PAGE)
        second = await call("onenote_read_page", page=_PAGE)

        assert "Retry once" in str(first.value)
        assert "decision one" in cast("str", second["html"])

    async def test_a_read_that_fails_twice_is_reported_and_not_to_be_repeated(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(return_value=httpx.Response(500, json=_BUSY))

        with pytest.raises(ToolError) as first:
            _ = await call("onenote_read_page", page=_PAGE)
        with pytest.raises(ToolError) as second:
            _ = await call("onenote_read_page", page=_PAGE)

        assert "Retry once" in str(first.value)
        assert "stop and report it" in str(second.value)

    async def test_a_page_of_a_team_that_the_person_may_not_open_names_the_membership(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_TEAM_PAGE_PATH).mock(return_value=httpx.Response(403, json=_BUSY))

        with pytest.raises(ToolError) as refused:
            _ = await call("onenote_read_page", page=_TEAM_PAGE)

        assert "is not a member of that group or site" in str(refused.value)
        assert "Ask the user to get access" in str(refused.value)

    async def test_a_missing_consent_is_explained_and_no_page_is_read(
        self, graph: respx.MockRouter
    ) -> None:
        async def refuse(_self: AzureProvider, **_: object) -> object:
            raise ClientAuthenticationError("AADSTS65001: the administrator never consented")

        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            patch.setattr(AzureProvider, "get_obo_credential", refuse)
            async with Client(FastMCPTransport(_server()), mode="legacy") as client:
                with pytest.raises(ToolError) as refused:
                    _ = await client.call_tool("onenote_read_page", {"page": _PAGE})

        assert "ask a Microsoft 365 administrator to grant" in str(refused.value)
        assert "sign in to this connector again" in str(refused.value)
        assert not graph.calls


class TestACreateThatFails:
    async def test_a_page_in_a_team_notebook_that_the_person_may_not_use_is_not_created(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/groups/{_GROUP_ID}/onenote/sections/{_SECTION_ID}").mock(
            return_value=httpx.Response(403, json=_BUSY)
        )
        create = graph.post(f"/groups/{_GROUP_ID}/onenote/sections/{_SECTION_ID}/pages")
        person = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "onenote_create_page",
                title="Retro",
                body_html="<p>x</p>",
                section=_TEAM_SECTION,
                person=person,
            )

        assert "is not a member of that group or site" in str(refused.value)
        assert (create.called, person.asked) == (False, [])

    async def test_a_busy_microsoft_is_given_the_time_it_asks_for_and_the_page_is_posted_once(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        _own_notes(graph)
        create = graph.post(f"/me/onenote/sections/{_SECTION_ID}/pages").mock(
            return_value=httpx.Response(429, headers={"retry-after": "30"}, json=_BUSY)
        )

        with pytest.raises(ToolError) as busy:
            _ = await call(
                "onenote_create_page", title="Weekly sync", body_html="<p>x</p>", section=_SECTION
            )

        assert "asked to be left alone for 30 seconds" in str(busy.value)
        assert (create.call_count, retry_sleeps.delays) == (1, [])

    @pytest.mark.parametrize(
        "failure",
        [httpx.Response(500, json=_BUSY), httpx.ReadTimeout("injected")],
        ids=["internal-error", "no-answer"],
    )
    async def test_a_page_that_microsoft_fails_to_create_is_posted_once_and_looked_for_first(
        self, graph: respx.MockRouter, failure: Failure
    ) -> None:
        _own_notes(graph)
        create = graph.post(f"/me/onenote/sections/{_SECTION_ID}/pages").mock(side_effect=[failure])

        with pytest.raises(ToolError) as unknown:
            _ = await call(
                "onenote_create_page", title="Weekly sync", body_html="<p>x</p>", section=_SECTION
            )

        assert create.call_count == 1
        assert "does not know if Microsoft 365 made the change" in str(unknown.value)
        assert "Do not call this tool again first" in str(unknown.value)
        assert "onenote_list_pages" in str(unknown.value)

    @pytest.mark.parametrize(
        ("status", "told"),
        [
            (401, "Ask the user to sign in to this connector again"),
            (403, "grant the delegated permission Notes.Create"),
            (404, "call onenote_list_notebooks again and take a fresh `uri` for the section"),
        ],
        ids=["sign-in-expired", "no-access", "section-gone"],
    )
    async def test_a_page_that_microsoft_will_not_create_is_explained(
        self, graph: respx.MockRouter, status: int, told: str
    ) -> None:
        _own_notes(graph)
        _ = graph.post(f"/me/onenote/sections/{_SECTION_ID}/pages").mock(
            return_value=httpx.Response(status, json=_BUSY)
        )

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "onenote_create_page", title="Weekly sync", body_html="<p>x</p>", section=_SECTION
            )

        assert told in str(refused.value)

    async def test_a_rejected_page_gives_the_reason_and_is_not_to_be_sent_again(
        self, graph: respx.MockRouter
    ) -> None:
        _own_notes(graph)
        reason = {"error": {"code": "20102", "message": "the page content is not well formed"}}
        _ = graph.post(f"/me/onenote/sections/{_SECTION_ID}/pages").mock(
            return_value=httpx.Response(400, json=reason)
        )

        with pytest.raises(ToolError) as rejected:
            _ = await call(
                "onenote_create_page", title="Weekly sync", body_html="<p>x", section=_SECTION
            )

        assert "the page content is not well formed" in str(rejected.value)
        assert "will fail the same way" in str(rejected.value)

    async def test_a_change_that_may_be_partly_done_is_to_be_checked_before_the_rest_is_sent(
        self, graph: respx.MockRouter
    ) -> None:
        _own_notes(graph)
        patch = graph.post(f"{_PAGE_PATH}/onenotePatchContent").mock(
            side_effect=httpx.ReadTimeout("injected")
        )
        commands = [
            {"target": "p:{b2}!2", "action": "replace", "content": "<p>Launch on 21 June</p>"},
            {"target": "body", "action": "append", "content": '<p data-tag="to-do">buy</p>'},
        ]
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            description = next(
                t.description for t in await client.list_tools() if t.name == "onenote_edit_page"
            )

        with pytest.raises(ToolError) as unknown:
            _ = await call("onenote_edit_page", page=_PAGE, commands=commands)

        assert patch.call_count == 1
        assert "does not know if Microsoft 365 made the change" in str(unknown.value)
        assert "onenote_read_page" in str(unknown.value)
        assert "resend only the missing commands" in (description or "")


class TestAPageOrPictureThatCannotBeRead:
    async def test_a_page_above_one_megabyte_is_refused_as_a_whole_with_its_web_address(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(return_value=httpx.Response(200, json=_page()))
        _ = graph.get(f"{_PAGE_PATH}/content").mock(return_value=_page_html(b"x" * (_MEGABYTE + 1)))

        with pytest.raises(ToolError) as refused:
            _ = await call("onenote_read_page", page=_PAGE)

        assert "1,048,577 bytes" in str(refused.value)
        assert _WEB_URL in str(refused.value)

    async def test_a_page_that_arrives_empty_is_blamed_on_microsoft(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(return_value=httpx.Response(200, json=_page()))
        _ = graph.get(f"{_PAGE_PATH}/content").mock(return_value=_page_html(b""))

        with pytest.raises(ToolError) as refused:
            _ = await call("onenote_read_page", page=_PAGE)

        assert "fault on Microsoft's side" in str(refused.value)
        assert "Ask for this page again later" in str(refused.value)
        assert "open the page in OneNote directly" in str(refused.value)

    async def test_an_address_that_names_no_notebook_is_reported_as_found_nothing(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.post("/me/onenote/notebooks/getNotebookFromWebUrl").mock(
            return_value=httpx.Response(404, json=_BUSY)
        )

        with pytest.raises(ToolError) as nothing:
            _ = await call(
                "onenote_find_notebook_from_url", web_url="https://contoso.example.invalid/nothing"
            )

        assert "found no notebook at this address" in str(nothing.value)
        assert "onenote_list_notebooks or onenote_list_recent_notebooks" in str(nothing.value)

    async def test_a_page_that_is_already_gone_is_not_erased_again(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(return_value=httpx.Response(404, json=_BUSY))
        delete = graph.delete(_PAGE_PATH)
        person = Person()

        with pytest.raises(ToolError) as gone:
            _ = await call("onenote_delete_page", page=_PAGE, person=person)

        assert "onenote_list_pages" in str(gone.value)
        assert (delete.called, person.asked) == (False, [])

    async def test_a_picture_above_ten_megabytes_is_refused_as_a_whole(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onenote/resources/RES1/content").mock(
            return_value=httpx.Response(
                200, content=b"x" * (10 * _MEGABYTE + 1), headers={"content-type": "image/png"}
            )
        )

        with pytest.raises(ToolError) as refused:
            _ = await _bytes_of("onenote_read_resource", resource=_PICTURE)

        assert "returns a resource of 10,485,760 bytes (10 MB) or less" in str(refused.value)

    async def test_a_picture_that_arrives_empty_is_blamed_on_microsoft(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onenote/resources/RES1/content").mock(
            return_value=httpx.Response(200, content=b"", headers={"content-type": "image/png"})
        )

        with pytest.raises(ToolError) as refused:
            _ = await _bytes_of("onenote_read_resource", resource=_PICTURE)

        assert "fault on Microsoft's side" in str(refused.value)
        assert "open the page that holds it in OneNote directly" in str(refused.value)

    async def test_a_picture_that_is_gone_sends_the_assistant_back_to_the_page(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onenote/resources/RES1/content").mock(
            return_value=httpx.Response(404, json=_BUSY)
        )

        with pytest.raises(ToolError) as gone:
            _ = await _bytes_of("onenote_read_resource", resource=_PICTURE)

        assert "Re-read the page that holds it with onenote_read_page" in str(gone.value)

    async def test_a_picture_on_a_page_is_given(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-onenote_read_resource-gallery")

        read = await call("onenote_read_page", page=await _gallery_page())
        address = unescape(
            cast("re.Match[str]", re.search(r'src="([^"]+)"', cast("str", read["html"])))[1]
        )
        picture = await _bytes_of("onenote_read_resource", resource=address)

        assert [key for key, route in routes.items() if not route.called] == []
        assert picture.startswith(b"\x89PNG")


def _onenote_reads(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if "/pages/" in path:
        return httpx.Response(200, json=_page())
    if "/sections/" in path or "/sectionGroups/" in path:
        return httpx.Response(200, json=_section())
    return httpx.Response(200, json=_notebook(shared="/groups/" in path))


_EDIT = {"target": "p:{b2}!2", "action": "replace", "content": "<p>Launch on 21 June</p>"}

_APPROVED_WRITES: list[tuple[str, Row]] = [
    ("onenote_delete_page", {"page": _PAGE}),
    ("onenote_edit_page", {"page": _PAGE, "commands": [_EDIT]}),
    ("onenote_create_page", {"title": "Retro", "body_html": "<p>x</p>", "section": _TEAM_SECTION}),
    ("onenote_copy_notebook", {"notebook": _NOTEBOOK, "to_group": _GROUP_ID}),
    ("onenote_copy_section", {"section": _SECTION, "to_notebook": _TEAM_NOTEBOOK}),
    ("onenote_copy_page", {"page": _PAGE, "to_section": _TEAM_SECTION}),
]
_WRITE_IDS = ["erase", "replace", "team-page", "notebook-copy", "section-copy", "page-copy"]


class TestAChangeThatIsNotApproved:
    @pytest.mark.parametrize(("tool", "arguments"), _APPROVED_WRITES, ids=_WRITE_IDS)
    async def test_a_declined_change_leaves_the_notes_as_they_were(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        _ = graph.route(method="GET").mock(side_effect=_onenote_reads)
        person = Person(approval="no")

        with pytest.raises(ToolError) as declined:
            _ = await _call(tool, arguments, person=person)

        assert "say that the request was not confirmed" in str(declined.value)
        assert "Do not call this tool again for the same request" in str(declined.value)
        assert len(person.asked) == 1
        assert {method for method, _ in _sent(graph)} == {"GET"}

    @pytest.mark.parametrize(("tool", "arguments"), _APPROVED_WRITES[:3], ids=_WRITE_IDS[:3])
    async def test_a_change_without_an_answer_does_not_happen_and_can_be_asked_again(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        _ = graph.route(method="GET").mock(side_effect=_onenote_reads)
        person = Person(approval="unanswered")

        with pytest.raises(ToolError) as unanswered:
            _ = await _call(tool, arguments, person=person)

        assert "received no answer" in str(unanswered.value)
        assert "they can make the same request again" in str(unanswered.value)
        assert {method for method, _ in _sent(graph)} == {"GET"}


class TestNamesAndNotebooks:
    async def test_a_notebook_name_that_is_already_used_creates_nothing_more(
        self, graph: respx.MockRouter
    ) -> None:
        create = graph.post("/me/onenote/notebooks").mock(
            return_value=httpx.Response(
                409, json={"error": {"code": "20127", "message": "duplicate"}}
            )
        )

        with pytest.raises(ToolError) as duplicate:
            _ = await call("onenote_create_notebook", name="Project Falcon")

        assert "already has the same name" in str(duplicate.value)
        assert "Change the name" in str(duplicate.value)
        assert create.call_count == 1

    @pytest.mark.parametrize(
        ("tool", "arguments", "limit"),
        [
            ("onenote_create_notebook", {}, 128),
            ("onenote_create_section", {"parent": _NOTEBOOK}, 50),
            ("onenote_create_section_group", {"parent": _NOTEBOOK}, 50),
        ],
        ids=["notebook", "section", "section-group"],
    )
    async def test_a_name_that_is_too_long_creates_nothing(
        self, graph: respx.MockRouter, tool: str, arguments: Row, limit: int
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, {**arguments, "name": "n" * (limit + 1)})

        assert f"at most {limit} characters" in str(refused.value)
        assert not graph.calls

    @pytest.mark.parametrize(
        ("tool", "fixture", "limit"),
        [
            ("onenote_create_notebook", "rec-tool-onenote_create_notebook-new", 128),
            ("onenote_create_section", "rec-tool-onenote_create_section-new", 50),
            ("onenote_create_section_group", "rec-tool-onenote_create_section_group-new", 50),
        ],
        ids=["notebook", "section", "section-group"],
    )
    async def test_a_name_of_the_longest_allowed_length_is_sent_whole(
        self, graph: respx.MockRouter, tool: str, fixture: str, limit: int
    ) -> None:
        routes = serve(graph, fixture)
        parent: Row = (
            {}
            if tool == "onenote_create_notebook"
            else {
                "parent": OnenoteNotebookHandle(_id_in(routes, "GET", "/me/onenote/notebooks/")).uri
            }
        )

        _ = await _call(tool, {**parent, "name": "n" * limit})

        [create] = [route for (verb, _), route in routes.items() if verb == "POST"]
        assert json.loads(create.calls.last.request.content)["displayName"] == "n" * limit

    async def test_a_section_refused_in_a_section_group_gets_the_generic_administrator_advice(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="GET").mock(side_effect=_onenote_reads)
        _ = graph.post("/me/onenote/sectionGroups/ARCHIVE/sections").mock(
            return_value=httpx.Response(403, json=_BUSY)
        )
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            description = next(
                t.description
                for t in await client.list_tools()
                if t.name == "onenote_create_section"
            )

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "onenote_create_section",
                parent=OnenoteSectionGroupHandle("ARCHIVE").uri,
                name="2025",
            )

        assert "Ask a Microsoft 365 administrator to grant the delegated permission" in str(
            refused.value
        )
        assert "Retrying will not help" in str(refused.value)
        assert "copy a section into the group" in (description or "")


def _operation(*, status: str = "Running", error: Row | None = None) -> Row:
    return {
        "id": _OPERATION_ID,
        "status": status,
        "createdDateTime": "2026-01-01T00:00:00Z",
        "lastActionDateTime": "2026-01-01T00:00:00Z",
        "error": error,
    }


class TestCopying:
    async def test_a_notebook_is_copied_under_a_new_name_and_followed_to_the_end(
        self, graph: respx.MockRouter
    ) -> None:
        copies = serve(graph, "rec-tool-onenote_copy_notebook-spare")
        notebook = OnenoteNotebookHandle(_id_in(copies, "POST", "/me/onenote/notebooks/")).uri
        started = await call("onenote_copy_notebook", notebook=notebook, new_name="Customers 2026")
        operation_id = unquote(str(started["uri"]).rsplit("/", 1)[1])
        finished = _operation(status="completed") | {
            "id": operation_id,
            "resourceId": "NEWNB",
            "resourceLocation": "https://graph.microsoft.com/v1.0/me/onenote/notebooks/NEWNB",
        }
        _ = graph.get(f"/me/onenote/operations/{operation_id}").mock(
            return_value=httpx.Response(200, json=finished)
        )

        state = await call("onenote_get_operation", operation=started["uri"])

        assert str(started["uri"]).startswith("onenote:///operations/")
        assert (state["status"], state["result_kind"]) == ("Completed", "notebook")
        assert state["result_uri"] == OnenoteNotebookHandle("NEWNB").uri
        assert {method for method, _ in _sent(graph)} == {"POST", "GET"}
        [post] = [path for method, path in _sent(graph) if method == "POST"]
        assert post.endswith("/copyNotebook")

    async def test_a_notebook_is_copied_into_a_team_after_the_person_approves(
        self, graph: respx.MockRouter
    ) -> None:
        copies = serve(graph, "rec-tool-onenote_copy_notebook-team")
        notebook_id = _id_in(copies, "POST", "/me/onenote/notebooks/")
        person = Person()

        _ = await call(
            "onenote_copy_notebook",
            notebook=OnenoteNotebookHandle(notebook_id).uri,
            to_group=_SEED_TEAM_ID,
            person=person,
        )

        [copy] = [route for (verb, _), route in copies.items() if verb == "POST"]
        assert json.loads(copy.calls.last.request.content)["groupId"] == _SEED_TEAM_ID
        assert len(person.asked) == 1
        assert _SEED_TEAM_ID in person.asked[0]

    async def test_a_section_is_copied_into_another_notebook(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-onenote_copy_section-notebook")
        section = OnenoteSectionHandle(_id_in(routes, "POST", "/me/onenote/sections/")).uri
        notebook = OnenoteNotebookHandle(
            _id_in(routes, "GET", "/me/onenote/notebooks/", whole=True)
        ).uri

        started = await call("onenote_copy_section", section=section, to_notebook=notebook)

        assert str(started["uri"]).startswith("onenote:///operations/")
        assert [method for method, _ in _sent(graph)] == ["GET", "POST"]

    async def test_a_page_is_copied_into_another_section(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-onenote_copy_page-section")
        page = OnenotePageHandle(_id_in(routes, "POST", "/me/onenote/pages/")).uri

        started = await call(
            "onenote_copy_page", page=page, to_section=OnenoteSectionHandle(_COPIES_SECTION).uri
        )

        assert str(started["uri"]).startswith("onenote:///operations/")
        assert [method for method, _ in _sent(graph)].count("POST") == 1

    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            ("onenote_copy_notebook", {"notebook": _SITE_NOTEBOOK}),
            ("onenote_copy_section", {"section": _SITE_SECTION, "to_notebook": _NOTEBOOK}),
        ],
        ids=["notebook", "section"],
    )
    async def test_nothing_is_copied_from_a_notebook_of_a_site(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, arguments)

        assert _SITE_REFUSED in str(refused.value)
        assert not graph.calls

    async def test_a_page_of_a_site_is_not_copied_but_its_content_is_written_again(
        self, graph: respx.MockRouter
    ) -> None:
        site_page = f"/sites/{_SITE.owner_id}/onenote/pages/{_PAGE_ID}"
        _ = graph.get(site_page).mock(return_value=httpx.Response(200, json=_page("Policy")))
        _ = graph.get(f"{site_page}/content").mock(
            return_value=_page_html(b"<html><body><p>retention is 7 years</p></body></html>")
        )
        _own_notes(graph)
        create = graph.post(f"/me/onenote/sections/{_SECTION_ID}/pages").mock(
            return_value=httpx.Response(201, json=_page("Policy"))
        )

        with pytest.raises(ToolError) as refused:
            _ = await call("onenote_copy_page", page=_SITE_PAGE, to_section=_SECTION)
        read = await call("onenote_read_page", page=_SITE_PAGE)
        _ = await call(
            "onenote_create_page",
            title="Policy",
            body_html="<p>retention is 7 years</p>",
            section=_SECTION,
        )

        assert _SITE_REFUSED in str(refused.value)
        assert "onenote_read_page" in str(refused.value)
        assert "retention is 7 years" in cast("str", read["html"])
        assert b"retention is 7 years" in create.calls.last.request.content
        assert not [path for _, path in _sent(graph) if path.endswith("copyToSection")]

    @pytest.mark.parametrize(
        "failure",
        [httpx.Response(500, json=_BUSY), httpx.ReadTimeout("injected")],
        ids=["internal-error", "no-answer"],
    )
    async def test_a_copy_that_microsoft_fails_is_started_once_and_looked_for_before_a_repeat(
        self, graph: respx.MockRouter, failure: Failure
    ) -> None:
        copy = graph.post(f"/me/onenote/notebooks/{_NOTEBOOK_ID}/copyNotebook").mock(
            side_effect=[failure]
        )

        with pytest.raises(ToolError) as unknown:
            _ = await call("onenote_copy_notebook", notebook=_NOTEBOOK, new_name="Customers 2026")

        assert copy.call_count == 1
        assert "does not know if Microsoft 365 made the change" in str(unknown.value)
        assert "onenote_list_notebooks" in str(unknown.value)

    async def test_a_copy_that_cannot_be_followed_is_looked_for_later_and_not_started_again(
        self, graph: respx.MockRouter
    ) -> None:
        copy = graph.post(f"/me/onenote/notebooks/{_NOTEBOOK_ID}/copyNotebook").mock(
            return_value=httpx.Response(202, content=b"")
        )

        with pytest.raises(ToolError) as untracked:
            _ = await call("onenote_copy_notebook", notebook=_NOTEBOOK, new_name="Customers 2026")

        assert "may still be running" in str(untracked.value)
        assert "do not call this tool again for the same copy" in str(untracked.value)
        assert copy.call_count == 1

    async def test_a_copy_that_microsoft_reports_as_failed_gives_the_reason(
        self, graph: respx.MockRouter
    ) -> None:
        failed = _operation(
            status="Failed", error={"code": "20101", "message": "the notebook is locked"}
        )
        _ = graph.get(f"/me/onenote/operations/{_OPERATION_ID}").mock(
            return_value=httpx.Response(200, json=failed)
        )

        state = await call(
            "onenote_get_operation", operation=OnenoteOperationHandle(_OPERATION_ID).uri
        )

        assert (state["status"], state["error_code"], state["error_message"]) == (
            "Failed",
            "20101",
            "the notebook is locked",
        )

    async def test_a_copy_that_microsoft_no_longer_knows_is_reported_as_unknown(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/onenote/operations/{_OPERATION_ID}").mock(
            return_value=httpx.Response(404, json=_BUSY)
        )

        with pytest.raises(ToolError) as unknown:
            _ = await call(
                "onenote_get_operation", operation=OnenoteOperationHandle(_OPERATION_ID).uri
            )

        assert "has no record of this operation" in str(unknown.value)


class TestARenameAHeadAndAPreview:
    async def test_a_page_is_renamed_and_only_its_title_is_sent(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-onenote_rename_page-seed")
        page = OnenotePageHandle(_id_in(routes, "GET", "/me/onenote/pages/")).uri

        renamed = await call("onenote_rename_page", page=page, title="Acme kickoff decisions")

        [patch] = [
            route for (_, path), route in routes.items() if path.endswith("onenotePatchContent")
        ]
        [command] = cast("list[Row]", json.loads(patch.calls.last.request.content)["commands"])
        assert (command["target"], command["action"]) == ("title", "Replace")
        assert "previous_title" in renamed

    async def test_the_start_of_a_page_is_shown_without_reading_the_page(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-onenote_preview_page-gallery")
        page = OnenotePageHandle(_id_in(routes, "GET", "/me/onenote/pages/")).uri

        shown = await call("onenote_preview_page", page=page)

        assert isinstance(shown["preview_text"], str)
        assert not [path for _, path in _sent(graph) if path.endswith("/content")]

    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            ("onenote_preview_page", {"page": _PAGE}),
            ("onenote_rename_page", {"page": _PAGE, "title": "Acme kickoff decisions"}),
            ("onenote_append_to_page", {"page": _PAGE, "body_html": "<p>x</p>"}),
        ],
        ids=["preview", "rename", "append"],
    )
    async def test_a_page_that_is_gone_is_looked_for_again_in_the_page_list(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(return_value=httpx.Response(404, json=_BUSY))
        _ = graph.get(f"{_PAGE_PATH}/preview()").mock(return_value=httpx.Response(404, json=_BUSY))

        with pytest.raises(ToolError) as gone:
            _ = await _call(tool, arguments)

        assert "most likely deleted" in str(gone.value)
        assert "onenote_list_pages" in str(gone.value)
        assert {method for method, _ in _sent(graph)} == {"GET"}

    @pytest.mark.parametrize(
        ("tool", "arguments", "told"),
        [
            (
                "onenote_append_to_page",
                {"page": _PAGE, "body_html": "<p>x</p>"},
                "Do not call onenote_append_to_page again",
            ),
            (
                "onenote_rename_page",
                {"page": _PAGE, "title": "Decisions"},
                "Use onenote_read_page to see the new title",
            ),
        ],
        ids=["append", "rename"],
    )
    async def test_a_change_that_was_made_but_cannot_be_shown_is_not_made_twice(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: str
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(
            side_effect=[httpx.Response(200, json=_page()), httpx.Response(500, json=_BUSY)]
        )
        _ = graph.get(f"/me/onenote/notebooks/{_NOTEBOOK_ID}").mock(
            return_value=httpx.Response(200, json=_notebook())
        )
        patch = graph.post(f"{_PAGE_PATH}/onenotePatchContent").mock(
            return_value=httpx.Response(204)
        )

        with pytest.raises(ToolError) as unread:
            _ = await _call(tool, arguments)

        assert told in str(unread.value)
        assert "onenote_read_page" in str(unread.value)
        assert patch.call_count == 1

    @pytest.mark.parametrize(
        "failure",
        [httpx.Response(500, json=_BUSY), httpx.ReadTimeout("injected")],
        ids=["internal-error", "no-answer"],
    )
    async def test_an_addition_that_microsoft_fails_is_sent_once_and_looked_for_before_a_repeat(
        self, graph: respx.MockRouter, failure: Failure
    ) -> None:
        _own_notes(graph)
        patch = graph.post(f"{_PAGE_PATH}/onenotePatchContent").mock(side_effect=[failure])

        with pytest.raises(ToolError) as unknown:
            _ = await call("onenote_append_to_page", page=_PAGE, body_html="<p>x</p>")

        assert patch.call_count == 1
        assert "does not know if Microsoft 365 made the change" in str(unknown.value)
        assert "onenote_read_page" in str(unknown.value)
