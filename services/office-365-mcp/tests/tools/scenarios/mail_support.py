import functools
import json
from collections.abc import Callable, Mapping, Sequence
from typing import cast
from urllib.parse import quote, unquote

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult

from tests.e2e.test_scenarios import Person, build_server, patch_obo
from tests.graph_fixtures import E2E, V1, Json, response

__all__ = [
    "a_draft_to_send",
    "asked_of",
    "handle_of",
    "marking_every_message",
    "moving_every_message",
    "FAULTS",
    "advice_for",
    "answers",
    "call_with",
    "raising",
    "every_time",
    "invoke_as",
    "methods_asked",
    "refusal_of",
    "folder_listing",
    "paths_asked",
    "search_of",
    "answer_of",
    "invoke",
    "mail_message",
    "sent_json",
    "sent_jsons",
    "serve_as",
    "times_asked",
    "tool_description",
    "tool_parameters",
]

FAULTS: Mapping[str, tuple[int, Mapping[str, str], str, str]] = {
    "signed-out": (
        401,
        {},
        "error.InvalidAuthenticationToken.json",
        "Ask the user to sign in to this connector again",
    ),
    "forbidden": (
        403,
        {},
        "error.accessDenied.json",
        "Ask a Microsoft 365 administrator to grant the delegated permission",
    ),
    "busy": (
        429,
        {"Retry-After": "30"},
        "error.TooManyRequests.json",
        "asked to be left alone for 30 seconds",
    ),
}


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


async def invoke_as(
    tool: str,
    arguments: Mapping[str, object],
    *,
    person: Person | None = None,
    can_ask: bool = True,
    patches: Sequence[Callable[[pytest.MonkeyPatch], None]] = (),
) -> CallToolResult:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        for apply in patches:
            apply(patch)
        async with Client(
            FastMCPTransport(_server()),
            elicitation_handler=(person or Person()) if can_ask else None,
            mode="legacy",
        ) as client:
            return await client.call_tool(tool, dict(arguments))


async def asked_of(tool: str, arguments: Mapping[str, object]) -> InputRequiredResult:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(FastMCPTransport(_server())) as client:
            first = await client.session.call_tool(tool, dict(arguments), allow_input_required=True)
    assert isinstance(first, InputRequiredResult), f"{tool} did not hand the question back"
    return first


async def call_with(tool: str, arguments: Mapping[str, object]) -> Mapping[str, object]:
    answered = (await invoke_as(tool, arguments)).structured_content
    assert answered is not None, f"{tool} answered with text only"
    return answered


async def invoke(tool: str, /, **arguments: object) -> CallToolResult:
    return await invoke_as(tool, arguments)


async def refusal_of(
    tool: str,
    arguments: Mapping[str, object],
    *,
    person: Person | None = None,
    can_ask: bool = True,
    patches: Sequence[Callable[[pytest.MonkeyPatch], None]] = (),
) -> str:
    with pytest.raises(ToolError) as refused:
        _ = await invoke_as(tool, arguments, person=person, can_ask=can_ask, patches=patches)
    return str(refused.value)


async def advice_for(tool: str, /, **arguments: object) -> str:
    return await refusal_of(tool, arguments)


def raising(failure: httpx.Response | Exception) -> Callable[[httpx.Request], httpx.Response]:
    def fail(_request: httpx.Request) -> httpx.Response:
        if isinstance(failure, Exception):
            raise failure
        return failure

    return fail


def every_time(body: Mapping[str, object]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(200, json=body)


def answers(spec: Json) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: response(spec)


def answer_of(fixture: str, method: str, path_start: str, *, nth: int = 0) -> dict[str, object]:
    interactions = cast(
        "list[Json]", json.loads((E2E / "fixtures" / f"{fixture}.json").read_text(encoding="utf-8"))
    )
    matching = [
        one
        for one in interactions
        if one["method"] == method and str(one["path"]).startswith(f"{V1}{path_start}")
    ]
    return cast("dict[str, object]", matching[nth]["response_json"])


def serve_as(
    router: respx.MockRouter, fixture: str, mailbox: str
) -> dict[tuple[str, str], respx.Route]:
    answers: dict[tuple[str, str], list[httpx.Response]] = {}
    for spec in cast(
        "list[Json]", json.loads((E2E / "fixtures" / f"{fixture}.json").read_text(encoding="utf-8"))
    ):
        path = str(spec["path"]).removeprefix(V1).replace("/me/", f"/users/{mailbox}/", 1)
        answers.setdefault((str(spec["method"]), path), []).append(response(spec))
    return {
        key: router.route(method=key[0], path=key[1]).mock(side_effect=responses)
        for key, responses in answers.items()
    }


def a_draft_to_send(
    router: respx.MockRouter,
    *,
    message_id: str = "DRAFT1=",
    change_keys: Sequence[str] = ("CK1", "CK1"),
    is_draft: bool = True,
) -> tuple[respx.Route, respx.Route]:
    stored = answer_of("rec-tool-outlook_send_draft-persona", "GET", "/me/messages/")
    reads = [
        httpx.Response(200, json=stored | {"id": message_id, "isDraft": is_draft, "changeKey": key})
        for key in change_keys
    ]
    read = router.get(f"/me/messages/{message_id}").mock(side_effect=reads)
    send = router.post(f"/me/messages/{message_id}/send").mock(return_value=httpx.Response(202))
    return read, send


def moving_every_message(router: respx.MockRouter) -> respx.Route:
    template = answer_of("rec-tool-outlook_move_mail-archive", "POST", "/me/messages/")

    def moved(request: httpx.Request) -> httpx.Response:
        message_id = unquote(request.url.path.split("/")[-2])
        return httpx.Response(201, json=template | {"id": message_id})

    return router.route(method="POST", path__regex=r".*/messages/[^/]+/move$").mock(
        side_effect=moved
    )


def marking_every_message(router: respx.MockRouter) -> respx.Route:
    def marked(request: httpx.Request) -> httpx.Response:
        asked = cast("dict[str, object]", json.loads(request.content))
        message_id = unquote(request.url.path.rsplit("/", 1)[-1])
        flag = cast("dict[str, object]", asked.get("flag", {}))
        return httpx.Response(
            200,
            json={
                "id": message_id,
                "isRead": asked.get("isRead", False),
                "importance": "normal",
                "flag": {"flagStatus": flag.get("flagStatus", "notFlagged")},
                "categories": asked.get("categories", []),
            },
        )

    _ = router.get(path__regex=r".*/messages/[^/]+$").mock(
        return_value=httpx.Response(200, json={"categories": []})
    )
    return router.route(method="PATCH", path__regex=r".*/messages/[^/]+$").mock(side_effect=marked)


def handle_of(message_id: str) -> str:
    return f"outlook:///messages/{quote(message_id, safe='')}"


def mail_message(
    message_id: str,
    subject: str,
    *,
    sender: str = "anna@example.test",
    received_at: str = "2026-03-04T09:15:00Z",
    is_read: bool = False,
    has_attachments: bool = False,
    conversation_id: str | None = None,
) -> dict[str, object]:
    message: dict[str, object] = {
        "id": message_id,
        "subject": subject,
        "bodyPreview": f"Preview of {subject}",
        "from": {"emailAddress": {"name": sender, "address": sender}},
        "sender": {"emailAddress": {"name": sender, "address": sender}},
        "toRecipients": [{"emailAddress": {"name": "Mia", "address": "mia@example.test"}}],
        "receivedDateTime": received_at,
        "isRead": is_read,
        "hasAttachments": has_attachments,
        "parentFolderId": "AQMkADAwSYNTHETIC-folder",
        "webLink": "https://outlook.office365.invalid/owa/?ItemID=synthetic",
        "importance": "normal",
        "flag": {"flagStatus": "notFlagged"},
        "categories": [],
        "isDraft": False,
    }
    if conversation_id is not None:
        message["conversationId"] = conversation_id
    return message


def folder_listing(
    router: respx.MockRouter,
    folder_path: str,
    *messages: dict[str, object],
    display_name: str,
    unread_items: int = 0,
) -> respx.Route:
    folder = {
        "displayName": display_name,
        "totalItemCount": len(messages),
        "unreadItemCount": unread_items,
    }
    _ = router.get(folder_path).mock(return_value=httpx.Response(200, json=folder))
    return router.get(f"{folder_path}/messages").mock(
        return_value=httpx.Response(200, json={"value": list(messages)})
    )


def requests_asked(router: respx.MockRouter) -> list[httpx.Request]:
    calls = cast("list[tuple[httpx.Request, httpx.Response | None]]", router.calls)
    return [request for request, _answer in calls]


def paths_asked(router: respx.MockRouter) -> list[str]:
    return [request.url.path for request in requests_asked(router)]


def sent_jsons(router: respx.MockRouter, method: str, path_end: str) -> list[dict[str, object]]:
    return [
        cast("dict[str, object]", json.loads(request.content))
        for request in requests_asked(router)
        if request.method == method and request.url.path.endswith(path_end)
    ]


def sent_json(router: respx.MockRouter, method: str, path_end: str) -> dict[str, object]:
    sent = sent_jsons(router, method, path_end)
    assert len(sent) == 1, f"{len(sent)} requests {method} ...{path_end} reached Graph"
    return sent[0]


def times_asked(router: respx.MockRouter, method: str, path_end: str) -> int:
    return sum(
        1
        for request in requests_asked(router)
        if request.method == method and request.url.path.endswith(path_end)
    )


def methods_asked(router: respx.MockRouter) -> set[str]:
    return {request.method for request in requests_asked(router)}


def search_of(router: respx.MockRouter) -> str:
    asked = [
        request.url.params["$search"]
        for request in requests_asked(router)
        if request.method == "GET" and "$search" in request.url.params
    ]
    assert len(asked) == 1, f"{len(asked)} searches reached Graph"
    return asked[0].removeprefix('"').removesuffix('"').replace('\\"', '"')


async def tool_description(tool: str) -> str:
    found = await _server().get_tool(tool)
    assert found is not None, f"{tool} is not registered"
    return found.description or ""


async def tool_parameters(tool: str) -> set[str]:
    found = await _server().get_tool(tool)
    assert found is not None, f"{tool} is not registered"
    return set(cast("Mapping[str, object]", found.parameters["properties"]))
