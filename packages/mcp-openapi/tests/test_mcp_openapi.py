import asyncio
import json
import re
import subprocess
import sys
from collections.abc import AsyncGenerator, Callable, Coroutine, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import cast

import httpx2
import pytest
import tenacity
import yaml
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType
from fastmcp.tools import Tool
from pydantic import BaseModel, TypeAdapter, ValidationError

from mcp_openapi.cli import main
from mcp_openapi.codegen import generate_operations, generate_response_models
from mcp_openapi.headers import only_headers
from mcp_openapi.lock import LockConfig, RequestLock
from mcp_openapi.openapi import mcp_name, route_map, set_tool_hints
from mcp_openapi.retry import RetryAfterPolicy, RetryPolicy
from mcp_openapi.upstream import LockTimeoutError, Operation, OperationClient, UpstreamError


class Row(BaseModel):
    value: int


ROWS = TypeAdapter(list[Row])
OBJECT = TypeAdapter(dict[str, object])

SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /things:
    get:
      operationId: getThings
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: array, items: {$ref: "#/components/schemas/Thing"}}
  /things/{name}:
    post:
      operationId: postThing
      parameters:
        - {name: name, in: path, required: true, schema: {type: string}}
        - {name: dry, in: query, schema: {type: boolean}}
        - {name: X-Trace, in: header, schema: {type: string}}
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [label]
              properties: {label: {type: string}, qty: {type: integer}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                properties: {ok: {type: boolean}, other: {type: string}}
    get:
      operationId: getThing
      parameters:
        - {name: name, in: path, required: true, schema: {type: string}}
        - {name: since, in: query, schema: {type: string}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Thing"}
components:
  schemas:
    Thing:
      type: object
      properties:
        name: {type: string, maxLength: 5, description: The name.}
        secret: {type: string}
        qty: {type: integer, minimum: 0, maximum: 10}
"""


def load_spec(text: str) -> dict[str, object]:
    return cast(dict[str, object], yaml.safe_load(text))


POST_THING_FIELDS = "                properties: {ok: {type: boolean}, other: {type: string}}\n"


def api(handler: Callable[[httpx2.Request], httpx2.Response]) -> OperationClient:
    http = httpx2.AsyncClient(
        base_url="https://upstream.example",
        headers={"Authorization": "Token k"},
        transport=httpx2.MockTransport(handler),
    )
    return OperationClient(load_spec(SPEC), http)


def get_things(body: object, status: int = 200) -> list[Row]:
    client = api(lambda _: httpx2.Response(status, json=body))
    return asyncio.run(client.call(Operation("getThings", ROWS)))


def test_operation_ids_lists_the_operations_of_the_spec() -> None:
    assert api(lambda _: httpx2.Response(200)).operation_ids == {
        "getThings",
        "getThing",
        "postThing",
    }


def test_call_parses_the_body_as_the_adapter_type() -> None:
    assert get_things([{"value": 1}, {"value": 2}]) == [Row(value=1), Row(value=2)]


def test_call_names_the_field_that_does_not_fit() -> None:
    with pytest.raises(UpstreamError, match=r"Unexpected response: 1\.value: "):
        get_things([{"value": 1}, {"value": "x"}])


def test_call_builds_the_request_from_the_spec() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"value": 1})

    asyncio.run(
        api(handler).call(Operation("getThing", TypeAdapter(Row)), name="a/b", since="2026-01-02")
    )
    request = seen[0]
    assert (request.method, request.url.raw_path) == (
        "GET",
        b"/things/a%2Fb?since=2026-01-02",
    )
    assert request.headers["authorization"] == "Token k"


def test_only_listed_headers_leave_and_fixed_ones_are_set() -> None:
    request = httpx2.Request(
        "GET",
        "https://upstream.example/",
        headers={
            "Authorization": "Bearer caller",
            "X-Forwarded-For": "203.0.113.9",
            "Accept": "*/*",
        },
    )
    asyncio.run(
        only_headers(
            frozenset({"accept"}), {"Authorization": "Token k"}, origin="https://upstream.example"
        )(request)
    )
    assert request.headers["authorization"] == "Token k"
    assert request.headers["accept"] == "*/*"
    assert "x-forwarded-for" not in request.headers


def test_call_error_does_not_include_the_query_string() -> None:
    client = api(lambda _: httpx2.Response(404))
    with pytest.raises(UpstreamError) as error:
        asyncio.run(client.call(Operation("getThing", TypeAdapter(Row)), name="a", since="SECRET"))
    assert str(error.value) == "404 Not Found for GET https://upstream.example/things/a"


def test_call_error_includes_the_start_of_the_response_body() -> None:
    client = api(lambda _: httpx2.Response(404, text='{"detail":"Not found."}'))
    with pytest.raises(UpstreamError, match=r'404 Not Found for GET .*: \{"detail":"Not found."\}'):
        asyncio.run(client.call(Operation("getThings", ROWS)))


def test_call_names_the_body_when_it_is_not_json() -> None:
    client = api(lambda _: httpx2.Response(200, content=b"<html>"))
    with pytest.raises(UpstreamError, match="Unexpected response: body: Invalid JSON"):
        asyncio.run(client.call(Operation("getThings", ROWS)))


def test_call_error_carries_the_status_of_an_error_response() -> None:
    with pytest.raises(UpstreamError) as error:
        get_things({"detail": "Not found."}, status=404)
    assert error.value.status_code == 404


def test_call_error_carries_no_status_when_the_body_does_not_fit() -> None:
    with pytest.raises(UpstreamError) as error:
        get_things([{"value": "x"}])
    assert error.value.status_code is None


def test_call_error_carries_no_status_when_the_upstream_does_not_answer() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(UpstreamError) as error:
        asyncio.run(api(refuse).call(Operation("getThings", ROWS)))
    assert error.value.status_code is None


def test_call_rejects_an_operation_that_is_not_in_the_spec() -> None:
    client = api(lambda _: httpx2.Response(200, json=[]))
    with pytest.raises(AssertionError, match="operationId getMissing is not in the spec"):
        asyncio.run(client.call(Operation("getMissing", ROWS)))


def test_call_sends_path_query_header_and_body_arguments_where_the_spec_puts_them() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={})

    arguments = {"name": "a/b", "dry": True, "X-Trace": "t1", "label": "x", "qty": 3}
    asyncio.run(api(handler).call(Operation("postThing", OBJECT), **arguments))
    request = seen[0]
    assert (request.method, request.url.raw_path) == ("POST", b"/things/a%2Fb?dry=true")
    assert request.headers["x-trace"] == "t1"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {"label": "x", "qty": 3}
    assert request.headers["authorization"] == "Token k"


def test_call_rejects_an_argument_the_spec_does_not_know() -> None:
    client = api(lambda _: httpx2.Response(200, json={"value": 1}))
    operation = Operation("getThing", TypeAdapter(Row))
    with pytest.raises(
        ValueError, match=r"getThing has no \['sinc'\], it takes \['name', 'since'\]"
    ):
        asyncio.run(client.call(operation, name="a", sinc="2026-01-02"))


@pytest.mark.parametrize(
    ("arguments", "missing"),
    [
        ({"label": "x"}, "['name']"),
        ({"name": "a"}, "['label']"),
        ({"name": "a", "label": None}, "['label']"),
        ({"name": "", "label": "x"}, "['name']"),
    ],
)
def test_call_rejects_a_required_argument_that_is_missing(
    arguments: dict[str, object], missing: str
) -> None:
    client = api(lambda _: httpx2.Response(200, json={}))
    with pytest.raises(ValueError, match=rf"postThing needs {re.escape(missing)}"):
        asyncio.run(client.call(Operation("postThing", OBJECT), **arguments))


def test_request_raw_sends_the_request_through_the_client_and_parses_the_body() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"value": 1})

    row = asyncio.run(
        api(handler).request_raw(
            "POST", "/hidden", TypeAdapter(Row), params={"dry": True}, json={"label": "x"}
        )
    )
    assert row == Row(value=1)
    request = seen[0]
    assert (request.method, request.url.raw_path) == ("POST", b"/hidden?dry=true")
    assert json.loads(request.content) == {"label": "x"}
    assert request.headers["authorization"] == "Token k"


def test_request_raw_names_the_field_that_does_not_fit() -> None:
    client = api(lambda _: httpx2.Response(200, json={"value": "x"}))
    with pytest.raises(UpstreamError, match=r"Unexpected response: value: "):
        asyncio.run(client.request_raw("GET", "/hidden", TypeAdapter(Row)))


@pytest.mark.parametrize("path", ["https://other.example/x", "//other.example/x", "hidden"])
def test_request_raw_rejects_anything_but_a_path(path: str) -> None:
    client = api(lambda _: httpx2.Response(200, json={"value": 1}))
    with pytest.raises(ValueError, match="is not a path"):
        asyncio.run(client.request_raw("GET", path, TypeAdapter(Row)))


RETRY_AFTER = RetryAfterPolicy()


def replay(
    responses: list[httpx2.Response], retry_policy: RetryPolicy | None = RETRY_AFTER
) -> tuple[list[Row] | UpstreamError, int]:
    """Answers each request with the next response, and returns the result and the count."""
    remaining = iter(responses)
    http = httpx2.AsyncClient(
        base_url="https://upstream.example",
        transport=httpx2.MockTransport(lambda _: next(remaining)),
    )
    client = OperationClient(load_spec(SPEC), http, retry_policy=retry_policy)
    try:
        result: list[Row] | UpstreamError = asyncio.run(client.call(Operation("getThings", ROWS)))
    except UpstreamError as error:
        result = error
    return result, len(responses) - len(list(remaining))


def rate_limited(retry_after: str | None = None) -> httpx2.Response:
    return httpx2.Response(429, headers={"Retry-After": retry_after} if retry_after else None)


def ok() -> httpx2.Response:
    return httpx2.Response(200, json=[{"value": 1}])


NO_BACKOFF = RetryAfterPolicy(max_attempts=3, backoff=tenacity.wait_none())


@pytest.mark.parametrize("status", [429, 503])
def test_default_policy_retries_after_the_delay_retry_after_asks_for(status: int) -> None:
    responses = [httpx2.Response(status, headers={"Retry-After": "0"}), ok()]
    assert replay(responses) == ([Row(value=1)], 2)


def test_default_policy_reads_retry_after_as_an_http_date() -> None:
    assert replay([rate_limited("Wed, 21 Oct 2015 07:28:00 GMT"), ok()]) == ([Row(value=1)], 2)


@pytest.mark.parametrize("retry_after", ["31", "Fri, 01 Jan 9999 00:00:00 GMT"])
def test_default_policy_gives_up_when_retry_after_asks_for_more_than_the_ceiling(
    retry_after: str,
) -> None:
    result, sent = replay([rate_limited(retry_after), ok()])
    assert sent == 1
    assert str(result).startswith("429 Too Many Requests for GET")


def test_policy_falls_back_to_backoff_without_retry_after_and_stops_after_max_attempts() -> None:
    result, sent = replay([rate_limited(), rate_limited(), rate_limited(), ok()], NO_BACKOFF)
    assert sent == 3
    assert isinstance(result, UpstreamError)


def test_policy_caps_backoff_at_the_ceiling() -> None:
    policy = RetryAfterPolicy(max_wait_seconds=0, backoff=tenacity.wait_fixed(3600))
    assert replay([rate_limited("not a date"), ok()], policy) == ([Row(value=1)], 2)


def test_policy_does_not_retry_a_status_it_does_not_list() -> None:
    result, sent = replay([httpx2.Response(500), ok()], NO_BACKOFF)
    assert sent == 1
    assert str(result) == "500 Internal Server Error for GET https://upstream.example/things"


def replay_write(method: str, responses: list[httpx2.Response]) -> tuple[Row | UpstreamError, int]:
    """`replay` for a request that writes."""
    remaining = iter(responses)
    http = httpx2.AsyncClient(
        base_url="https://upstream.example",
        transport=httpx2.MockTransport(lambda _: next(remaining)),
    )
    client = OperationClient(load_spec(SPEC), http, retry_policy=NO_BACKOFF)
    try:
        result: Row | UpstreamError = asyncio.run(
            client.request_raw(method, "/hidden", TypeAdapter(Row), json={"label": "x"})
        )
    except UpstreamError as error:
        result = error
    return result, len(responses) - len(list(remaining))


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
def test_policy_sends_a_rate_limited_write_again(method: str) -> None:
    assert replay_write(method, [rate_limited(), httpx2.Response(200, json={"value": 1})]) == (
        Row(value=1),
        2,
    )


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_policy_sends_an_idempotent_write_again_on_a_503(method: str) -> None:
    responses = [httpx2.Response(503), httpx2.Response(200, json={"value": 1})]
    assert replay_write(method, responses) == (Row(value=1), 2)


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_policy_does_not_send_a_non_idempotent_write_again_on_a_503(method: str) -> None:
    result, sent = replay_write(
        method, [httpx2.Response(503), httpx2.Response(200, json={"value": 1})]
    )
    assert sent == 1
    assert str(result) == f"503 Service Unavailable for {method} https://upstream.example/hidden"


def test_no_policy_sends_a_request_once() -> None:
    result, sent = replay([rate_limited("0"), ok()], retry_policy=None)
    assert sent == 1
    assert isinstance(result, UpstreamError)


class SemaphoreLock:
    """A `RequestLock` over an `asyncio.Semaphore`, as a service could write one."""

    def __init__(self, limit: int) -> None:
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(limit)

    @asynccontextmanager
    async def hold(self, _request: httpx2.Request) -> AsyncGenerator[None]:
        async with self._semaphore:
            yield


class RecordingLock:
    def __init__(self) -> None:
        self.held: list[tuple[str, bytes, str | None]] = []

    @asynccontextmanager
    async def hold(self, request: httpx2.Request) -> AsyncGenerator[None]:
        authorization = request.headers.get("authorization")
        self.held.append((request.method, request.url.raw_path, authorization))
        yield


def locked_api(
    handler: Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]],
    lock: RequestLock,
    acquire_timeout_seconds: float = 30,
) -> OperationClient:
    http = httpx2.AsyncClient(
        base_url="https://upstream.example",
        headers={"Authorization": "Token k"},
        transport=httpx2.MockTransport(handler),
    )
    lock_config = LockConfig(lock=lock, acquire_timeout_seconds=acquire_timeout_seconds)
    return OperationClient(load_spec(SPEC), http, retry_policy=RETRY_AFTER, lock_config=lock_config)


async def answer_ok(_: httpx2.Request) -> httpx2.Response:
    return ok()


def test_the_lock_is_held_while_the_request_is_in_flight() -> None:
    in_flight: list[int] = [0]
    peak: list[int] = [0]

    async def handler(_: httpx2.Request) -> httpx2.Response:
        in_flight[0] += 1
        peak[0] = max(peak[0], in_flight[0])
        await asyncio.sleep(0.01)
        in_flight[0] -= 1
        return ok()

    async def run() -> None:
        client = locked_api(handler, SemaphoreLock(2))
        await asyncio.gather(*(client.call(Operation("getThings", ROWS)) for _ in range(5)))

    asyncio.run(run())
    assert peak[0] == 2


def test_a_request_fails_when_the_lock_is_not_acquired_in_time() -> None:
    async def run() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def handler(_: httpx2.Request) -> httpx2.Response:
            started.set()
            await release.wait()
            return ok()

        client = locked_api(handler, SemaphoreLock(1), acquire_timeout_seconds=0.01)
        first = asyncio.create_task(client.call(Operation("getThings", ROWS)))
        await started.wait()
        with pytest.raises(
            LockTimeoutError,
            match=r"No lock acquired within 0\.01s for GET https://upstream\.example/things$",
        ):
            await client.call(Operation("getThings", ROWS))
        release.set()
        assert await first == [Row(value=1)]

    asyncio.run(run())


def test_the_lock_is_released_after_a_failed_request() -> None:
    responses = iter([httpx2.Response(500), ok()])

    async def handler(_: httpx2.Request) -> httpx2.Response:
        return next(responses)

    async def run() -> list[Row]:
        client = locked_api(handler, SemaphoreLock(1), acquire_timeout_seconds=0.01)
        with pytest.raises(UpstreamError):
            await client.call(Operation("getThings", ROWS))
        return await client.call(Operation("getThings", ROWS))

    assert asyncio.run(run()) == [Row(value=1)]


def test_the_lock_is_held_per_attempt_with_the_request() -> None:
    responses = iter([rate_limited("0"), httpx2.Response(200, json={"value": 1})])

    async def handler(_: httpx2.Request) -> httpx2.Response:
        return next(responses)

    lock = RecordingLock()
    client = locked_api(handler, lock, acquire_timeout_seconds=5)
    asyncio.run(client.call(Operation("getThing", TypeAdapter(Row)), name="a", since="2026-01-02"))
    attempt = ("GET", b"/things/a?since=2026-01-02", "Token k")
    assert lock.held == [attempt, attempt]


def test_request_raw_holds_the_lock_with_its_request() -> None:
    lock = RecordingLock()
    client = locked_api(answer_ok, lock)
    asyncio.run(client.request_raw("POST", "/hidden", ROWS, params={"dry": True}))
    assert lock.held == [("POST", b"/hidden?dry=true", "Token k")]


def test_only_acquiring_the_lock_counts_against_the_timeout() -> None:
    async def slow(_: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(0.05)
        return ok()

    client = locked_api(slow, SemaphoreLock(1), acquire_timeout_seconds=0.01)
    assert asyncio.run(client.call(Operation("getThings", ROWS))) == [Row(value=1)]


def test_a_timeout_error_of_the_lock_itself_is_not_reported_as_a_lock_timeout() -> None:
    class BrokenLock:
        def hold(self, _request: httpx2.Request) -> BrokenLock:
            return self

        async def __aenter__(self) -> None:
            raise TimeoutError("socket timed out")

        async def __aexit__(self, *_: object) -> None:
            return None

    client = locked_api(answer_ok, BrokenLock())
    with pytest.raises(TimeoutError, match="socket timed out") as error:
        asyncio.run(client.call(Operation("getThings", ROWS)))
    assert not isinstance(error.value, LockTimeoutError)


def test_lock_config_rejects_something_that_is_not_a_lock() -> None:
    with pytest.raises(ValidationError, match="Input should be an instance of RequestLock"):
        LockConfig.model_validate({"lock": object(), "acquire_timeout_seconds": 1})


def redirected_authorization(
    location: str, origin: str = "https://upstream.example"
) -> list[tuple[str, str | None]]:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((str(request.url), request.headers.get("authorization")))
        if len(seen) == 1:
            return httpx2.Response(301, headers={"location": location})
        return httpx2.Response(200, json=[])

    hook = only_headers(frozenset({"host"}), {"Authorization": "Token k"}, origin=origin)

    async def run() -> None:
        async with httpx2.AsyncClient(
            follow_redirects=True,
            transport=httpx2.MockTransport(handler),
            event_hooks={"request": [hook]},
        ) as client:
            await client.get("https://upstream.example/start")

    asyncio.run(run())
    return seen


@pytest.mark.parametrize(
    "location",
    ["https://other.example/x", "http://upstream.example/x", "https://upstream.example:8443/x"],
)
def test_authorization_is_not_sent_to_another_origin_on_a_redirect(location: str) -> None:
    assert redirected_authorization(location) == [
        ("https://upstream.example/start", "Token k"),
        (location, None),
    ]


def test_authorization_follows_a_redirect_within_the_origin() -> None:
    seen = redirected_authorization("https://upstream.example/x")
    assert [auth for _, auth in seen] == ["Token k", "Token k"]


def test_origin_is_matched_case_insensitively() -> None:
    seen = redirected_authorization("https://upstream.example/x", origin="https://Upstream.Example")
    assert seen[0] == ("https://upstream.example/start", "Token k")


def test_the_headers_a_request_cannot_be_sent_without_are_always_kept() -> None:
    request = httpx2.Request("POST", "https://upstream.example/", content=b"{}")
    request.headers["X-Other"] = "1"
    asyncio.run(only_headers(frozenset(), {}, origin="https://upstream.example")(request))
    assert {"host", "content-length"} <= set(request.headers)
    assert "x-other" not in request.headers


def test_allow_list_names_are_case_insensitive() -> None:
    request = httpx2.Request("GET", "https://upstream.example/", headers={"Accept": "*/*"})
    asyncio.run(only_headers(frozenset({"Accept"}), {}, origin="https://upstream.example")(request))
    assert request.headers["accept"] == "*/*"


def generate(
    tmp_path: Path,
    fields: dict[str, tuple[str, ...]] | None = None,
    spec_path: Path | None = None,
    spec_url: str | None = None,
    client: httpx2.Client | None = None,
) -> str:
    output = tmp_path / "models.py"
    generate_response_models(
        operation_ids=["getThings"],
        fields={"Thing": ("name",)} if fields is None else fields,
        output=output,
        spec_path=spec_path,
        spec_url=spec_url,
        client=client,
    )
    return output.read_text()


def test_generated_model_is_trimmed_to_the_listed_fields(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    models = generate(tmp_path, spec_path=spec)
    assert "class Thing(BaseModel)" in models
    assert 'name: str | None = Field(None, description="The name.")' in models
    assert "secret" not in models


def test_spec_is_fetched_from_a_url_with_the_given_client(tmp_path: Path) -> None:
    client = httpx2.Client(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=SPEC))
    )
    models = generate(tmp_path, spec_url="https://spec.example/openapi.yml", client=client)
    assert "class Thing(BaseModel)" in models


def test_exactly_one_spec_source_is_required(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="exactly one"):
        generate(tmp_path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('swagger: "2.0"\n', "got no openapi field"),
        ("<html>not a spec</html>", "got no openapi field"),
        ("key: value: other\n", "not valid YAML or JSON"),
        ("openapi: 3.1.0\n", "got 3.1.0"),
    ],
)
def test_a_spec_the_generator_cannot_use_is_rejected(
    tmp_path: Path, content: str, message: str
) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(content)
    with pytest.raises(ValueError, match=message):
        generate(tmp_path, spec_path=spec)


def test_an_operation_missing_from_the_spec_is_named(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    with pytest.raises(AssertionError, match=r"not in the spec: \['getMissing'\]"):
        generate_response_models(
            spec_path=spec,
            operation_ids=["getMissing"],
            fields={},
            output=tmp_path / "models.py",
        )


def test_input_bounds_are_not_carried_into_the_models(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    models = generate(tmp_path, spec_path=spec, fields={})
    assert "qty: int | None" in models
    assert "ge=" not in models and "le=" not in models


def test_a_fields_key_that_names_no_generated_model_is_rejected(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(SPEC)
    with pytest.raises(AssertionError, match=r"not generated: \['Thnig'\]"):
        generate(tmp_path, spec_path=spec, fields={"Thnig": ("name",)})


def test_operations_without_a_named_response_schema_are_rejected(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(
        SPEC.replace(
            'schema: {type: array, items: {$ref: "#/components/schemas/Thing"}}',
            "schema: {type: array}",
        )
    )
    with pytest.raises(ValueError, match="has a response schema to generate"):
        generate(tmp_path, spec_path=spec)


def operations_for(tmp_path: Path, operation_ids: list[str], spec_text: str = SPEC) -> str:
    spec = tmp_path / "spec.yml"
    spec.write_text(spec_text)
    output = tmp_path / "operations.py"
    generate_operations(
        spec_path=spec,
        operation_ids=operation_ids,
        operation_module="mcp_openapi.upstream",
        models_module="models",
        output=output,
    )
    return output.read_text()


def test_each_operation_gets_a_constant_typed_with_its_response(tmp_path: Path) -> None:
    generated = operations_for(tmp_path, ["getThings", "getThing"])
    assert 'GET_THINGS = Operation[list[Thing]]("getThings", TypeAdapter(list[Thing]))' in generated
    assert 'GET_THING = Operation[Thing]("getThing", TypeAdapter(Thing))' in generated
    assert "from models import Thing\n" in generated


def test_generated_operations_keep_first_party_and_third_party_imports_apart(
    tmp_path: Path,
) -> None:
    (tmp_path / "models.py").write_text("")
    (tmp_path / "ruff.toml").write_text('src = ["."]\n')
    operations_for(tmp_path, ["getThings"])
    subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "I", str(tmp_path / "operations.py")],
        check=True,
        cwd=tmp_path,
    )


def test_a_constant_for_an_operation_without_an_object_or_named_response_is_refused(
    tmp_path: Path,
) -> None:
    spec_text = SPEC.replace(" " * 16 + "type: object\n", " " * 16 + "type: string\n")
    assert POST_THING_FIELDS in spec_text
    with pytest.raises(ValueError, match="postThing: the success response is not an object"):
        operations_for(tmp_path, ["postThing"], spec_text)


def test_a_response_written_in_place_gets_a_model_named_after_its_operation(
    tmp_path: Path,
) -> None:
    generated = operations_for(tmp_path, ["postThing"])
    assert (
        'POST_THING = Operation[PostThingResponse]("postThing", TypeAdapter(PostThingResponse))'
        in generated
    )
    assert "from models import PostThingResponse\n" in generated


def models_for(
    tmp_path: Path,
    spec_text: str,
    operation_ids: list[str],
    fields: dict[str, tuple[str, ...]] | None = None,
    allow_extra_fields: bool = False,
    snake_case_fields: bool = True,
) -> str:
    spec = tmp_path / "spec.yml"
    spec.write_text(spec_text)
    output = tmp_path / "models.py"
    generate_response_models(
        spec_path=spec,
        operation_ids=operation_ids,
        fields=fields,
        allow_extra_fields=allow_extra_fields,
        snake_case_fields=snake_case_fields,
        output=output,
    )
    return output.read_text()


def _model(tmp_path: Path, name: str) -> type[BaseModel]:
    module = ModuleType("generated_models")
    sys.modules[module.__name__] = module
    source = (tmp_path / "models.py").read_text()
    exec(compile(source, str(tmp_path / "models.py"), "exec"), module.__dict__)  # noqa: S102
    return cast(type[BaseModel], getattr(module, name))


def validated(tmp_path: Path, name: str, payload: Mapping[str, object]) -> dict[str, object]:
    return _model(tmp_path, name).model_validate(payload).model_dump()


def test_models_drop_undeclared_fields_unless_asked_to_keep_them(tmp_path: Path) -> None:
    body = {"name": "a", "unknown": "x"}
    models_for(tmp_path, SPEC, ["getThing"])
    assert "unknown" not in validated(tmp_path, "Thing", body)
    models_for(tmp_path, SPEC, ["getThing"], allow_extra_fields=True)
    assert validated(tmp_path, "Thing", body)["unknown"] == "x"


def test_a_field_cut_by_fields_stays_as_an_extra_when_extra_fields_are_kept(
    tmp_path: Path,
) -> None:
    models_for(tmp_path, SPEC, ["getThing"], fields={"Thing": ("name",)}, allow_extra_fields=True)
    assert "secret" not in _model(tmp_path, "Thing").model_fields
    assert validated(tmp_path, "Thing", {"name": "a", "secret": "s"})["secret"] == "s"


CASED_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /bar:
    get:
      operationId: getBar
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Bar"}
components:
  schemas:
    Bar:
      type: object
      properties:
        adjClose: {type: number}
        start-date: {type: string}
"""


def test_fields_are_snake_case_validate_from_the_spec_names_and_dump_back_to_them(
    tmp_path: Path,
) -> None:
    models_for(tmp_path, CASED_SPEC, ["getBar"])
    bar = _model(tmp_path, "Bar").model_validate({"adjClose": 1.5, "start-date": "2024-01-02"})

    assert bar.model_dump() == {"adj_close": 1.5, "start_date": "2024-01-02"}
    assert bar.model_dump(by_alias=True) == {"adjClose": 1.5, "start-date": "2024-01-02"}


def test_fields_keep_the_spec_names_when_snake_case_is_turned_off(tmp_path: Path) -> None:
    models_for(tmp_path, CASED_SPEC, ["getBar"], snake_case_fields=False)

    assert set(_model(tmp_path, "Bar").model_fields) == {"adjClose", "start_date"}


STRICT_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /strict:
    get:
      operationId: getStrict
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Strict"}
components:
  schemas:
    Strict:
      type: object
      additionalProperties: false
      properties: {a: {type: string}, secret: {type: string}}
"""


def test_a_model_trimmed_to_fields_accepts_the_fields_it_cut(tmp_path: Path) -> None:
    models_for(tmp_path, STRICT_SPEC, ["getStrict"], fields={"Strict": ("a",)})
    assert validated(tmp_path, "Strict", {"a": "1", "secret": "s"}) == {"a": "1"}


def test_a_model_written_for_a_response_in_place_has_the_fields_of_that_response(
    tmp_path: Path,
) -> None:
    generated = models_for(tmp_path, SPEC, ["postThing"])
    assert "class PostThingResponse(BaseModel):" in generated
    assert "ok: bool | None" in generated


def test_fields_trim_a_model_written_for_a_response_in_place(tmp_path: Path) -> None:
    generated = models_for(tmp_path, SPEC, ["postThing"], fields={"PostThingResponse": ("ok",)})
    assert "ok: bool | None" in generated
    assert "other" not in generated


def test_an_object_without_fields_is_not_made_into_an_empty_model(tmp_path: Path) -> None:
    spec_text = SPEC.replace(POST_THING_FIELDS, "")
    with pytest.raises(ValueError, match="postThing: the success response is not an object"):
        operations_for(tmp_path, ["postThing"], spec_text)


ONE_OF_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /either:
    get:
      operationId: get-either
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                oneOf:
                  - $ref: "#/components/schemas/A"
                  - $ref: "#/components/schemas/B"
components:
  schemas:
    A: {type: object, properties: {a: {type: string}}}
    B: {type: object, properties: {b: {type: string}}}
"""


def test_a_oneof_response_written_in_place_is_generated_with_its_alternatives(
    tmp_path: Path,
) -> None:
    generated = models_for(tmp_path, ONE_OF_SPEC, ["get-either"])
    assert "GetEitherResponse" in generated
    assert "A | B" in generated


def test_two_operations_cannot_make_the_same_model_name(tmp_path: Path) -> None:
    spec_text = ENVELOPE_SPEC.replace("components:", SECOND_COMPANIES_PATH + "components:")
    with pytest.raises(AssertionError, match="two operationIds make the model name"):
        models_for(tmp_path, spec_text, ["get-companies", "getCompanies"])


def test_two_operations_cannot_make_the_same_constant_name(tmp_path: Path) -> None:
    spec_text = SPEC.replace("operationId: getThing\n", "operationId: get-things\n")
    with pytest.raises(AssertionError, match="same constant name"):
        operations_for(tmp_path, ["getThings", "get-things"], spec_text)


def test_an_operation_id_that_does_not_make_a_valid_name_is_refused(tmp_path: Path) -> None:
    spec_text = SPEC.replace("operationId: postThing", "operationId: 2fa-status")
    with pytest.raises(AssertionError, match="invalid model name"):
        models_for(tmp_path, spec_text, ["2fa-status"])


SECOND_COMPANIES_PATH = """  /other:
    get:
      operationId: getCompanies
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: object, properties: {x: {type: string}}}
"""

ENVELOPE_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /companies:
    get:
      operationId: get-companies
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                allOf:
                  - $ref: "#/components/schemas/BaseResponse"
                  - type: object
                    properties:
                      data: {type: array, items: {$ref: "#/components/schemas/Company"}}
components:
  schemas:
    BaseResponse:
      type: object
      properties: {details: {type: string}}
    Company:
      type: object
      properties: {name: {type: string}}
"""


def test_an_allof_envelope_written_in_place_is_generated_with_the_schemas_it_uses(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(ENVELOPE_SPEC)
    models = tmp_path / "models.py"
    generate_response_models(spec_path=spec, operation_ids=["get-companies"], output=models)
    generated = models.read_text()
    assert "class GetCompaniesResponse(BaseResponse):" in generated
    assert "data: list[Company] | None" in generated
    assert (
        'GET_COMPANIES = Operation[GetCompaniesResponse]("get-companies", '
        "TypeAdapter(GetCompaniesResponse))"
    ) in operations_for(tmp_path, ["get-companies"], ENVELOPE_SPEC)


def test_a_model_name_made_from_an_operation_cannot_replace_a_schema_of_the_spec(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(
        ENVELOPE_SPEC.replace(
            "    Company:", "    GetCompaniesResponse:\n      type: object\n    Company:"
        )
    )
    with pytest.raises(AssertionError, match=r"already has \['GetCompaniesResponse'\]"):
        generate_response_models(
            spec_path=spec, operation_ids=["get-companies"], output=tmp_path / "models.py"
        )


def test_a_constant_for_an_operation_missing_from_the_spec_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match=r"not in the spec: \['getMissing'\]"):
        operations_for(tmp_path, ["getMissing"])


NESTED_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /parents:
    get:
      operationId: getParents
      responses:
        "200": {$ref: "#/components/responses/Parents"}
  /dangling:
    get:
      operationId: getDangling
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Missing"}
components:
  responses:
    Parents:
      description: ok
      content:
        application/json; charset=utf-8:
          schema: {type: array, items: {$ref: "#/components/schemas/Parent"}}
  schemas:
    Parent:
      type: object
      properties:
        kid: {$ref: "#/components/schemas/Kid"}
      additionalProperties: {$ref: "#/components/schemas/Extra"}
    Kid:
      type: object
      properties:
        leaf: {allOf: [{$ref: "#/components/schemas/Leaf"}]}
    Leaf: {type: object, properties: {name: {type: string}}}
    Extra: {type: object, properties: {note: {type: string}}}
    Unused: {type: object, properties: {name: {type: string}}}
"""


def models_from_nested_spec(tmp_path: Path, operation_id: str) -> Path:
    spec = tmp_path / "spec.yml"
    spec.write_text(NESTED_SPEC)
    output = tmp_path / "models.py"
    generate_response_models(spec_path=spec, operation_ids=[operation_id], fields={}, output=output)
    return output


def test_every_schema_a_response_reaches_is_generated_and_no_other(tmp_path: Path) -> None:
    models = models_from_nested_spec(tmp_path, "getParents").read_text()
    classes = {
        line.split("(")[0].removeprefix("class ")
        for line in models.splitlines()
        if line.startswith("class ")
    }
    assert classes == {"Parent", "Kid", "Leaf", "Extra"}


def test_a_response_that_refers_to_a_missing_schema_is_named(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="Missing is referenced but not in components.schemas"):
        models_from_nested_spec(tmp_path, "getDangling")


def test_a_response_defined_in_components_is_resolved(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yml"
    spec.write_text(NESTED_SPEC)
    output = tmp_path / "operations.py"
    generate_operations(
        spec_path=spec,
        operation_ids=["getParents"],
        operation_module="mcp_openapi.upstream",
        models_module="models",
        output=output,
    )
    assert (
        'GET_PARENTS = Operation[list[Parent]]("getParents", TypeAdapter(list[Parent]))'
        in output.read_text()
    )


@pytest.mark.parametrize(
    ("operation_id", "remove_prefix", "expected"),
    [
        ("getDailyPrices", "", "get_daily_prices"),
        ("getDailyPrices", "get_", "daily_prices"),
        ("testConnection", "get_", "test_connection"),
        ("get-companies-kyckrId", "", "get_companies_kyckr_id"),
        ("post-orders", "post_", "orders"),
        ("get2FaStatus", "", "get2_fa_status"),
    ],
)
def test_mcp_name_is_snake_case_for_camel_and_kebab_case_ids(
    operation_id: str, remove_prefix: str, expected: str
) -> None:
    assert mcp_name(operation_id, remove_prefix=remove_prefix) == expected


def served_tools(exposed: dict[str, MCPType]) -> dict[str, Tool]:
    mcp = FastMCP.from_openapi(
        openapi_spec=load_spec(SPEC),
        client=httpx2.AsyncClient(base_url="https://upstream.example"),
        route_map_fn=route_map(exposed),
        mcp_component_fn=set_tool_hints,
    )
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def test_route_map_serves_the_listed_operations_and_hides_the_rest() -> None:
    assert set(served_tools({"getThings": MCPType.TOOL, "postThing": MCPType.TOOL})) == {
        "getThings",
        "postThing",
    }


def test_generated_tools_are_open_world_and_read_only_only_for_get() -> None:
    tools = served_tools({"getThings": MCPType.TOOL, "postThing": MCPType.TOOL})
    hints = {
        name: (tool.annotations.read_only_hint, tool.annotations.open_world_hint)
        for name, tool in tools.items()
        if tool.annotations
    }
    assert hints == {"getThings": (True, True), "postThing": (False, True)}


SHAPES_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /typed:
    get:
      operationId: get-typed
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                allOf:
                  - $ref: "#/components/schemas/Base"
                  - properties: {rows: {type: array, items: {$ref: "#/components/schemas/Row"}}}
  /untyped:
    get:
      operationId: get-untyped
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                properties: {total: {type: integer}}
  /empty:
    delete:
      operationId: delete-empty
      responses:
        "204": {description: gone}
components:
  schemas:
    Base:
      type: object
      properties: {kind: {type: string, enum: [a], pattern: "^a$"}}
    Row:
      type: object
      properties: {size: {type: integer, minimum: 1}, tag: {type: string, enum: [x]}}
"""

_OK = """        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Thing"}"""
_ACCEPTED_THEN_OK = (
    """        "202":
          description: accepted
          content:
            application/json:
              schema: {type: array, items: {$ref: "#/components/schemas/Thing"}}
"""
    + _OK
)
TWO_CODES_SPEC = SPEC.replace(_OK, _ACCEPTED_THEN_OK)


def test_an_object_with_allof_or_with_fields_but_no_type_is_a_model_written_in_place(
    tmp_path: Path,
) -> None:
    models_for(tmp_path, SHAPES_SPEC, ["get-typed", "get-untyped"])
    assert validated(tmp_path, "GetUntypedResponse", {"total": 3}) == {"total": 3}
    assert validated(tmp_path, "GetTypedResponse", {"kind": "a"})["kind"] == "a"


def test_input_constraints_are_not_carried_into_the_models_inside_allof_and_arrays(
    tmp_path: Path,
) -> None:
    models_for(tmp_path, SHAPES_SPEC, ["get-typed"])
    reply = validated(
        tmp_path, "GetTypedResponse", {"kind": "other", "rows": [{"size": 0, "tag": "other"}]}
    )
    assert reply["kind"] == "other"
    assert reply["rows"] == [{"size": 0, "tag": "other"}]


def test_a_response_without_a_json_body_is_named(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="delete-empty: the success response has no JSON body"):
        operations_for(tmp_path, ["delete-empty"], SHAPES_SPEC)


def test_an_operation_id_without_letters_or_digits_is_refused(tmp_path: Path) -> None:
    spec_text = SPEC.replace("operationId: getThings", 'operationId: "--"')
    with pytest.raises(AssertionError, match="invalid constant name"):
        operations_for(tmp_path, ["--"], spec_text)
    spec_text = SPEC.replace("operationId: postThing", 'operationId: "--"')
    with pytest.raises(AssertionError, match="no letters or digits"):
        models_for(tmp_path, spec_text, ["--"])


def test_an_operation_id_with_characters_a_name_would_lose_is_refused(tmp_path: Path) -> None:
    spec_text = SPEC.replace("operationId: getThings", "operationId: getÜbersicht")
    with pytest.raises(AssertionError, match="characters"):
        operations_for(tmp_path, ["getÜbersicht"], spec_text)


def test_the_lowest_success_code_gives_the_model_of_an_operation(tmp_path: Path) -> None:
    generated = operations_for(tmp_path, ["getThing"], TWO_CODES_SPEC)
    assert 'GET_THING = Operation[Thing]("getThing", TypeAdapter(Thing))' in generated


def test_arguments_that_are_none_are_not_sent() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"name": "a"})

    asyncio.run(api(handler).call(Operation("getThing", OBJECT), name="a", since=None))

    assert seen[0].url.query == b""


def test_a_timeout_is_an_upstream_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    with pytest.raises(UpstreamError, match="timed out"):
        asyncio.run(api(handler).call(Operation("getThings", ROWS)))


def test_the_error_body_in_the_message_is_cut_at_200_characters() -> None:
    with pytest.raises(UpstreamError) as raised:
        get_things({"detail": "x" * 500}, status=502)
    assert len(str(raised.value)) < 300


INLINE_ONLY_SPEC = """
openapi: 3.0.3
info: {title: t, version: "1"}
paths:
  /in:
    get:
      operationId: getIn
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: object, properties: {a: {type: string}}}
  /map:
    get:
      operationId: getMap
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {type: object, additionalProperties: {type: string}}
"""


def test_a_spec_without_components_generates_the_models_written_in_place(tmp_path: Path) -> None:
    models_for(tmp_path, INLINE_ONLY_SPEC, ["getIn"])
    assert validated(tmp_path, "GetInResponse", {"a": "x"}) == {"a": "x"}


def test_a_response_that_is_a_map_is_a_model_written_in_place(tmp_path: Path) -> None:
    models_for(tmp_path, INLINE_ONLY_SPEC, ["getMap"])
    assert validated(tmp_path, "GetMapResponse", {"any": "x"}) == {"any": "x"}


def test_an_operation_id_with_a_quote_still_writes_a_module_that_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_text = SPEC.replace("operationId: getThings", 'operationId: "get\\"x"')
    models_for(tmp_path, spec_text, ["getThing"])
    generated = operations_for(tmp_path, ['get"x'], spec_text)
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    monkeypatch.delitem(sys.modules, "models", raising=False)
    namespace: dict[str, object] = {}
    exec(compile(generated, "operations.py", "exec"), namespace)  # noqa: S102
    operation = cast(Operation[object], namespace["GET_X"])
    assert operation.operation_id == 'get"x'


def test_an_operation_id_with_characters_a_model_name_would_lose_is_refused(
    tmp_path: Path,
) -> None:
    spec_text = SPEC.replace("operationId: postThing", "operationId: postÜbersicht")
    with pytest.raises(AssertionError, match="characters a name would lose"):
        models_for(tmp_path, spec_text, ["postÜbersicht"])


CODEGEN_CONFIG = """
[tool.mcp-openapi]
spec = "spec.yml"
operation-ids = ["getThings"]
operation-module = "mcp_openapi.upstream"
models-module = "models"
models-output = "out/models.py"
operations-output = "out/operations.py"
"""


def test_cli_generates_models_and_operations_from_the_pyproject_table(tmp_path: Path) -> None:
    (tmp_path / "spec.yml").write_text(SPEC)
    (tmp_path / "pyproject.toml").write_text(
        CODEGEN_CONFIG + '[tool.mcp-openapi.fields]\nThing = ["name"]\n'
    )
    (tmp_path / "out").mkdir()

    main([str(tmp_path)])

    assert "class Thing(BaseModel)" in (tmp_path / "out/models.py").read_text()
    assert "GET_THINGS" in (tmp_path / "out/operations.py").read_text()


def test_cli_generates_models_for_more_operations_than_it_makes_constants_for(
    tmp_path: Path,
) -> None:
    (tmp_path / "spec.yml").write_text(SPEC)
    config = CODEGEN_CONFIG.replace(
        'operation-ids = ["getThings"]',
        'operation-ids = ["getThings"]\nresponse-operation-ids = ["getThings", "postThing"]',
    )
    (tmp_path / "pyproject.toml").write_text(config)
    (tmp_path / "out").mkdir()

    main([str(tmp_path)])

    assert "POST_THING" not in (tmp_path / "out/operations.py").read_text()
    assert "PostThingResponse" in (tmp_path / "out/models.py").read_text()


def test_cli_rejects_an_unknown_key_in_the_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(CODEGEN_CONFIG + "operation-id = []\n")

    with pytest.raises(ValidationError, match="operation-id"):
        main([str(tmp_path)])


def test_cli_imports_an_operation_id_list_given_as_module_and_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "codegen_routes_fixture.py").write_text(
        'IDS = ["getThings"]\nFIELDS = {"Thing": ("name",)}\n'
    )
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    (tmp_path / "spec.yml").write_text(SPEC)
    (tmp_path / "pyproject.toml").write_text(
        CODEGEN_CONFIG.replace('["getThings"]', '"codegen_routes_fixture:IDS"')
        + 'fields = "codegen_routes_fixture:FIELDS"\n'
    )
    (tmp_path / "out").mkdir()

    main([str(tmp_path)])

    assert "GET_THINGS" in (tmp_path / "out/operations.py").read_text()
    assert "secret" not in (tmp_path / "out/models.py").read_text()


def test_cli_rejects_an_operation_id_reference_without_a_name(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(CODEGEN_CONFIG.replace('["getThings"]', '"routes"'))

    with pytest.raises(ValidationError, match="module:NAME"):
        main([str(tmp_path)])


def codegen_project(tmp_path: Path, config: str = CODEGEN_CONFIG) -> Path:
    (tmp_path / "spec.yml").write_text(SPEC)
    (tmp_path / "pyproject.toml").write_text(config)
    (tmp_path / "out").mkdir()
    return tmp_path


def test_cli_check_passes_when_the_generated_files_are_current(tmp_path: Path) -> None:
    main([str(codegen_project(tmp_path))])

    main([str(tmp_path), "--check"])


def test_cli_check_fails_on_a_stale_file_and_leaves_it_as_it_was(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main([str(codegen_project(tmp_path))])
    operations = tmp_path / "out/operations.py"
    edited = operations.read_text().replace("GET_THINGS", "GET_ROWS")
    operations.write_text(edited)

    with pytest.raises(SystemExit) as exit_info:
        main([str(tmp_path), "--check"])

    assert exit_info.value.code == 1
    assert f"{operations} is stale:" in capsys.readouterr().out
    assert operations.read_text() == edited


def test_cli_check_fails_on_a_file_never_generated_and_does_not_leave_it(tmp_path: Path) -> None:
    codegen_project(tmp_path)

    with pytest.raises(SystemExit) as exit_:
        main([str(tmp_path), "--check"])

    assert exit_.value.code == 1
    assert not (tmp_path / "out/models.py").exists()


def test_cli_refresh_spec_vendors_a_json_source_as_yaml_and_regenerates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = CODEGEN_CONFIG.replace(
        'spec = "spec.yml"', 'spec = "spec.yml"\nspec-source = "v2.json"'
    )
    codegen_project(tmp_path, config)
    vendor = load_spec(SPEC)
    paths = cast(dict[str, dict[str, object]], vendor["paths"])
    del paths["/things/{name}"]["post"]
    paths["/rows"] = paths["/things"]
    (tmp_path / "v2.json").write_text(json.dumps(vendor))

    main([str(tmp_path), "--refresh-spec"])

    assert load_spec((tmp_path / "spec.yml").read_text()) == vendor
    assert not (tmp_path / "spec.yml").read_text().startswith("{")
    assert capsys.readouterr().out == "operationIds changed:\n- postThing\n"
    assert "GET_THINGS" in (tmp_path / "out/operations.py").read_text()


def test_cli_refresh_spec_needs_a_spec_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_:
        main([str(codegen_project(tmp_path)), "--refresh-spec"])

    assert exit_.value.code == 2
    assert "--refresh-spec needs spec and spec-source" in capsys.readouterr().err


def test_cli_rejects_a_spec_source_without_a_vendored_spec(tmp_path: Path) -> None:
    config = CODEGEN_CONFIG.replace(
        'spec = "spec.yml"', 'spec-url = "https://x"\nspec-source = "y"'
    )

    with pytest.raises(ValidationError, match="spec-source"):
        main([str(codegen_project(tmp_path, config))])
