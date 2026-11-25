import json
from collections.abc import Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphUnavailable
from office_365_mcp.shared.outlook.tasks import TaskLink
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.outlook_add_task_link import add_task_link

_LIST_ID = "AAMkSYNTHETIClist0001"
_TASK_ID = "AAMkSYNTHETICtask0001"
_LINK_ID = "SYNTHETIC-link-0001"
_TASK = f"outlook:///tasks/{_LIST_ID}/{_TASK_ID}"
_ONE_LIST = f"/me/todo/lists/{_LIST_ID}"
_LINKS = f"{_ONE_LIST}/tasks/{_TASK_ID}/linkedResources"
_WEB_URL = "https://outlook.office365.com/owa/?ItemID=AAMkSYNTHETICmessage0001"
_NOTHING_ADDED = "No link was added."


def _list_is(graph: respx.MockRouter, *, shared: bool | None) -> respx.Route:
    listed: dict[str, object] = {"id": _LIST_ID, "displayName": "Launch"}
    if shared is not None:
        listed["isShared"] = shared
    return graph.get(_ONE_LIST).mock(return_value=httpx.Response(200, json=listed))


def _posted(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_LINKS).mock(
        return_value=httpx.Response(
            201,
            json={
                "id": _LINK_ID,
                "webUrl": _WEB_URL,
                "displayName": "Q3 report",
                "applicationName": "Outlook",
            },
        )
    )


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a write in a private list was put to a person: {question!r} ({about})")


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_ADDED


async def _add(
    client: GraphServiceClient,
    *,
    uri: str = _TASK,
    web_url: str = _WEB_URL,
    application: str = "Outlook",
    confirm: Confirm = _never_asked,
) -> TaskLink:
    answer = await add_task_link(
        client,
        uri=uri,
        web_url=web_url,
        title="Q3 report",
        application=application,
        confirm=confirm,
    )
    assert isinstance(answer, TaskLink), "this call was answered with a question"
    return answer


def _body(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


class TestWhatItSendsToGraph:
    async def test_it_posts_the_address_the_title_and_the_app(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list_is(graph, shared=False)
        post = _posted(graph)

        answer = await _add(client)

        assert _body(post) == {
            "webUrl": _WEB_URL,
            "displayName": "Q3 report",
            "applicationName": "Outlook",
        }
        assert answer.uri == f"{_TASK}/links/{_LINK_ID}"
        assert (answer.title, answer.web_url, answer.application) == (
            "Q3 report",
            _WEB_URL,
            "Outlook",
        )

    async def test_it_sends_the_app_that_the_caller_names(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list_is(graph, shared=False)
        post = _posted(graph)

        _ = await _add(client, application="SharePoint")

        assert _body(post)["applicationName"] == "SharePoint"

    async def test_it_posts_once_with_no_retry(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list_is(graph, shared=False)
        post = graph.post(_LINKS).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _add(client)

        assert post.call_count == 1


class TestWhatItRefusesBeforeAnyCall:
    async def test_a_handle_that_is_not_a_task_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_tasks") as raised:
            _ = await _add(client, uri=f"outlook:///tasklists/{_LIST_ID}")

        assert _NOTHING_ADDED in str(raised.value)
        assert cast("Sequence[Call]", graph.calls) == []

    @pytest.mark.parametrize(
        "web_url",
        [
            "http://example.invalid/report",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "outlook.office365.com/owa",
            "https://",
        ],
    )
    async def test_an_address_that_is_not_https_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter, web_url: str
    ) -> None:
        with pytest.raises(ToolError, match="`https`") as raised:
            _ = await _add(client, web_url=web_url)

        assert _NOTHING_ADDED in str(raised.value)
        assert cast("Sequence[Call]", graph.calls) == []


class TestAListThatOthersShare:
    async def test_the_question_names_the_link_and_the_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list_is(graph, shared=True)
        post = _posted(graph)
        asked: list[str] = []

        async def capture(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _add(client, confirm=capture)

        assert asked == [
            f"Add the link 'Q3 report', which opens {_WEB_URL!r}, to a task in the list 'Launch', "
            + "which other people share. They see the change?"
        ]
        assert post.call_count == 1

    async def test_a_list_that_does_not_say_if_it_is_shared_asks_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list_is(graph, shared=None)
        post = _posted(graph)

        _ = await _add(client, confirm=_agrees)

        assert post.call_count == 1

    async def test_a_person_who_declines_gets_no_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list_is(graph, shared=True)
        post = _posted(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _add(client, confirm=_refuses)

        assert str(raised.value) == _NOTHING_ADDED
        assert post.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_comes_back_before_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _list_is(graph, shared=True)
        post = _posted(graph)
        pending = InputRequiredResult(input_requests={}, request_state="state")

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return pending

        answer = await add_task_link(
            client, uri=_TASK, web_url=_WEB_URL, title="Q3 report", confirm=ask_back
        )

        assert answer is pending
        assert post.call_count == 0
