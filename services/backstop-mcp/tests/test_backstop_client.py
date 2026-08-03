import asyncio
import base64
import time

import httpx
import pytest
import respx
from pydantic import BaseModel, SecretStr, ValidationError

from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopAuthError,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
    BackstopUnreachableError,
    DeleteRequest,
    GetRequest,
    PageResult,
    PaginateRequest,
    PatchRequest,
    PostRequest,
    build_auth_headers,
    create_backstop_client,
    verify_credential,
)
from backstop_mcp.config import BackstopConfig

_BASE_URL = "https://example.backstopsolutions.com"
_BASIC_AUTH = "Basic " + base64.b64encode(b"bob.smith:p@55W0rd321!").decode()


def _credential(
    username: str = "bob.smith", api_token: str = "p@55W0rd321!"
) -> BackstopCredentialSecret:
    return BackstopCredentialSecret(username=username, api_token=SecretStr(api_token))


class TestBuildAuthHeaders:
    def test_builds_basic_auth_and_token_header(self) -> None:
        headers = build_auth_headers("bob.smith", "p@55W0rd321!")

        assert headers == {"authorization": _BASIC_AUTH, "token": "true"}


class TestCreateBackstopClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_builds_client_scoped_to_the_credential(self) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(200, json={})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            await client.get(GetRequest(path="/system-info"))

        sent_request = route.calls.last.request
        assert sent_request.headers["authorization"] == _BASIC_AUTH
        assert sent_request.headers["token"] == "true"


class TestBackstopClientAutoRaises:
    """The wrapper `create_backstop_client` returns maps every error response into a typed
    exception — tool implementations never need to check status codes themselves."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_backstop_auth_error_on_401(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(401))

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            with pytest.raises(BackstopAuthError):
                await client.get(GetRequest(path="/system-info"))

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_backstop_api_error_on_other_error_statuses(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "Something broke"}]})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            with pytest.raises(BackstopApiError) as exc_info:
                await client.get(GetRequest(path="/system-info"))

        assert exc_info.value.detail == "Something broke"

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_raise_on_200(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(200, json={"version": "1.0"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.get(GetRequest(path="/system-info"))

        assert result == {"version": "1.0"}


class TestHeaders:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_shared_defaults_and_per_call_authorization(self) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(200, json={})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            await client.get(GetRequest(path="/system-info"))

        sent_request = route.calls.last.request
        assert sent_request.headers["token"] == "true"
        assert sent_request.headers["accept"] == "application/vnd.api+json"
        assert sent_request.headers["content-type"] == "application/vnd.api+json"
        assert sent_request.headers["authorization"] == _BASIC_AUTH


class TestTimeoutProfiles:
    @pytest.mark.asyncio
    @respx.mock
    async def test_reports_path_uses_extended_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        respx.get(f"{_BASE_URL}/reports").mock(return_value=httpx.Response(200, json={}))
        captured_timeouts: list[object] = []

        from backstop_mcp.backstop_client import client as client_module

        shared_client = await client_module._get_shared_client()  # pyright: ignore[reportPrivateUsage]
        original_request = shared_client.request

        async def spy_request(*args: object, **kwargs: object) -> httpx.Response:
            captured_timeouts.append(kwargs["timeout"])
            return await original_request(*args, **kwargs)  # pyright: ignore[reportArgumentType]

        monkeypatch.setattr(shared_client, "request", spy_request)

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            await client.get(GetRequest(path="/reports"))

        assert captured_timeouts == [BackstopConfig().reports_timeout_seconds]

    @pytest.mark.asyncio
    @respx.mock
    async def test_crud_path_uses_default_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        respx.get(f"{_BASE_URL}/deals/1").mock(return_value=httpx.Response(200, json={}))
        captured_timeouts: list[object] = []

        from backstop_mcp.backstop_client import client as client_module

        shared_client = await client_module._get_shared_client()  # pyright: ignore[reportPrivateUsage]
        original_request = shared_client.request

        async def spy_request(*args: object, **kwargs: object) -> httpx.Response:
            captured_timeouts.append(kwargs["timeout"])
            return await original_request(*args, **kwargs)  # pyright: ignore[reportArgumentType]

        monkeypatch.setattr(shared_client, "request", spy_request)

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            await client.get(GetRequest(path="/deals/1"))

        assert captured_timeouts == [BackstopConfig().default_timeout_seconds]


class TestConcurrencySemaphore:
    @pytest.mark.asyncio
    @respx.mock
    async def test_at_most_five_requests_in_flight_for_one_username(self) -> None:
        release = asyncio.Event()
        in_flight = 0
        max_in_flight = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await release.wait()
            in_flight -= 1
            return httpx.Response(200, json={})

        respx.get(f"{_BASE_URL}/system-info").mock(side_effect=handler)
        credential = _credential(username="concurrency.user")

        async def call() -> dict[str, object]:
            async with create_backstop_client(_BASE_URL, credential) as client:
                return await client.get(GetRequest(path="/system-info"))

        tasks = [asyncio.create_task(call()) for _ in range(6)]
        await asyncio.sleep(0.05)

        assert max_in_flight == 5
        assert in_flight == 5

        release.set()
        await asyncio.gather(*tasks)
        assert max_in_flight == 5

    @pytest.mark.asyncio
    @respx.mock
    async def test_different_usernames_have_independent_semaphores(self) -> None:
        release = asyncio.Event()
        in_flight = 0
        max_in_flight = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await release.wait()
            in_flight -= 1
            return httpx.Response(200, json={})

        respx.get(f"{_BASE_URL}/system-info").mock(side_effect=handler)
        credential_a = _credential(username="user.a")
        credential_b = _credential(username="user.b")

        async def call(credential: BackstopCredentialSecret) -> dict[str, object]:
            async with create_backstop_client(_BASE_URL, credential) as client:
                return await client.get(GetRequest(path="/system-info"))

        tasks = [asyncio.create_task(call(credential_a)) for _ in range(5)]
        tasks += [asyncio.create_task(call(credential_b)) for _ in range(5)]
        await asyncio.sleep(0.05)

        assert max_in_flight == 10
        assert in_flight == 10

        release.set()
        await asyncio.gather(*tasks)


class TestRetryIntegration:
    @pytest.mark.asyncio
    @respx.mock
    async def test_succeeds_after_two_concurrency_retries(self) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            side_effect=[
                httpx.Response(
                    429,
                    json={
                        "errors": [{"detail": "Concurrency limit exceeded", "code": "concurrency"}]
                    },
                    headers={"Retry-After": "0.01"},
                ),
                httpx.Response(
                    429,
                    json={
                        "errors": [{"detail": "Concurrency limit exceeded", "code": "concurrency"}]
                    },
                    headers={"Retry-After": "0.01"},
                ),
                httpx.Response(200, json={"version": "1.0"}),
            ]
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.get(GetRequest(path="/system-info"))

        assert result == {"version": "1.0"}
        assert route.call_count == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_quota_breach_raises_immediately(self) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(
                429, json={"errors": [{"detail": "Daily quota exceeded", "code": "day"}]}
            )
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            with pytest.raises(BackstopRateLimitError) as exc_info:
                await client.get(GetRequest(path="/system-info"))

        assert exc_info.value.limit_kind == "day"
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_after_exceeding_ceiling_raises_immediately_without_sleeping(
        self,
    ) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(
                429,
                json={"errors": [{"detail": "Concurrency limit exceeded", "code": "concurrency"}]},
                headers={"Retry-After": "9999"},
            )
        )
        config = BackstopConfig(base_url=_BASE_URL, max_retry_wait_ms=1_000)

        from backstop_mcp.backstop_client.client import BackstopClient

        client = BackstopClient(_credential(), config, None)

        start = time.monotonic()
        with pytest.raises(BackstopRateLimitError):
            await client.get(GetRequest(path="/system-info"))
        elapsed = time.monotonic() - start

        assert route.call_count == 1
        assert elapsed < 0.5


class TestPaginate:
    @pytest.mark.asyncio
    @respx.mock
    async def test_delegates_to_paginate_all_across_multiple_pages(self) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "1"}],
                        "links": {"next": "/records?page[cursor]=abc"},
                    },
                ),
                httpx.Response(200, json={"data": [{"id": "2"}], "links": {"next": None}}),
            ]
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.paginate(PaginateRequest(path="/records"))

        assert result == PageResult(
            items=[{"id": "1"}, {"id": "2"}], total_count=None, truncated=False
        )


class _Record(BaseModel):
    id: str


class _Widget(BaseModel):
    id: str
    label: str


class TestSchemaAwareDeserialization:
    """`get`/`post`/`patch`/`delete` all funnel through the same `_deserialize` helper, so each
    verb gets the same three cases: `schema=None` returns a plain dict unchanged, a schema with
    a matching body returns a parsed model, and a schema with a mismatched body raises
    `BackstopResponseSchemaError` wrapping the underlying `pydantic.ValidationError`.

    `schema=None` regression coverage for GET already exists in
    `TestBackstopClientAutoRaises.test_does_not_raise_on_200` — not duplicated here.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_without_schema_returns_dict(self) -> None:
        respx.post(f"{_BASE_URL}/widgets").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.post(PostRequest(path="/widgets"))

        assert result == {"id": "1", "label": "Widget One"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_patch_without_schema_returns_dict(self) -> None:
        respx.patch(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.patch(PatchRequest(path="/widgets/1"))

        assert result == {"id": "1", "label": "Widget One"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_without_schema_returns_dict(self) -> None:
        respx.delete(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.delete(DeleteRequest(path="/widgets/1"))

        assert result == {"id": "1", "label": "Widget One"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_with_schema_returns_parsed_model(self) -> None:
        respx.get(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.get(GetRequest(path="/widgets/1", schema=_Widget))

        assert isinstance(result, _Widget)
        assert result.id == "1"
        assert result.label == "Widget One"

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_with_schema_returns_parsed_model(self) -> None:
        respx.post(f"{_BASE_URL}/widgets").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.post(PostRequest(path="/widgets", schema=_Widget))

        assert isinstance(result, _Widget)
        assert result.id == "1"
        assert result.label == "Widget One"

    @pytest.mark.asyncio
    @respx.mock
    async def test_patch_with_schema_returns_parsed_model(self) -> None:
        respx.patch(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.patch(PatchRequest(path="/widgets/1", schema=_Widget))

        assert isinstance(result, _Widget)
        assert result.id == "1"
        assert result.label == "Widget One"

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_with_schema_returns_parsed_model(self) -> None:
        respx.delete(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.delete(DeleteRequest(path="/widgets/1", schema=_Widget))

        assert isinstance(result, _Widget)
        assert result.id == "1"
        assert result.label == "Widget One"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_with_schema_mismatch_raises_schema_error(self) -> None:
        # Missing the required `label` field.
        respx.get(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": "1"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            with pytest.raises(BackstopResponseSchemaError) as exc_info:
                await client.get(GetRequest(path="/widgets/1", schema=_Widget))

        assert exc_info.value.path == "/widgets/1"
        assert exc_info.value.schema_name == "_Widget"
        assert isinstance(exc_info.value.cause, ValidationError)
        assert exc_info.value.__cause__ is exc_info.value.cause

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_with_schema_mismatch_raises_schema_error(self) -> None:
        # `label` is the wrong type (int, not str).
        respx.post(f"{_BASE_URL}/widgets").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": 123})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            with pytest.raises(BackstopResponseSchemaError) as exc_info:
                await client.post(PostRequest(path="/widgets", schema=_Widget))

        assert exc_info.value.path == "/widgets"
        assert exc_info.value.schema_name == "_Widget"
        assert isinstance(exc_info.value.cause, ValidationError)
        assert exc_info.value.__cause__ is exc_info.value.cause

    @pytest.mark.asyncio
    @respx.mock
    async def test_patch_with_schema_mismatch_raises_schema_error(self) -> None:
        # Missing the required `id` field.
        respx.patch(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"label": "Widget One"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            with pytest.raises(BackstopResponseSchemaError) as exc_info:
                await client.patch(PatchRequest(path="/widgets/1", schema=_Widget))

        assert exc_info.value.path == "/widgets/1"
        assert exc_info.value.schema_name == "_Widget"
        assert isinstance(exc_info.value.cause, ValidationError)
        assert exc_info.value.__cause__ is exc_info.value.cause

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_with_schema_mismatch_raises_schema_error(self) -> None:
        # `id` is the wrong type (int, not str).
        respx.delete(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": 1, "label": "Widget One"})
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            with pytest.raises(BackstopResponseSchemaError) as exc_info:
                await client.delete(DeleteRequest(path="/widgets/1", schema=_Widget))

        assert exc_info.value.path == "/widgets/1"
        assert exc_info.value.schema_name == "_Widget"
        assert isinstance(exc_info.value.cause, ValidationError)
        assert exc_info.value.__cause__ is exc_info.value.cause


class TestPaginateSchemaAwareDeserialization:
    """`schema=None` regression coverage for `paginate` already exists in
    `TestPaginate.test_delegates_to_paginate_all_across_multiple_pages` — not duplicated here.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_multi_page_walk_parses_every_item(self) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "1"}, {"id": "2"}],
                        "links": {"next": "/records?page[cursor]=abc"},
                    },
                ),
                httpx.Response(200, json={"data": [{"id": "3"}], "links": {}}),
            ]
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.paginate(PaginateRequest(path="/records", schema=_Record))

        assert [item.id for item in result.items] == ["1", "2", "3"]
        assert all(isinstance(item, _Record) for item in result.items)
        assert result.total_count is None
        assert result.truncated is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_mismatch_on_later_page_raises_for_whole_call(self) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={"data": [{"id": "1"}], "links": {"next": "/records?page[cursor]=abc"}},
                ),
                httpx.Response(200, json={"data": [{"not_id": "2"}], "links": {}}),
            ]
        )

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            with pytest.raises(BackstopResponseSchemaError) as exc_info:
                await client.paginate(PaginateRequest(path="/records", schema=_Record))

        assert route.call_count == 2
        assert exc_info.value.path == "/records"
        assert exc_info.value.schema_name == "_Record"
        assert isinstance(exc_info.value.cause, ValidationError)
        assert exc_info.value.__cause__ is exc_info.value.cause


class TestDeleteEmptyBody:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_for_204_with_no_body(self) -> None:
        respx.delete(f"{_BASE_URL}/records/1").mock(return_value=httpx.Response(204))

        async with create_backstop_client(_BASE_URL, _credential()) as client:
            result = await client.delete(DeleteRequest(path="/records/1"))

        assert result is None


class TestVerifyCredential:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_true_on_200(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(200))

        assert await verify_credential("bob.smith", "token", _BASE_URL) is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_false_on_401(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(401))

        assert await verify_credential("bob.smith", "wrong-token", _BASE_URL) is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_false_on_403(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(403))

        assert await verify_credential("bob.smith", "wrong-token", _BASE_URL) is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_unreachable_on_5xx(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(503))

        with pytest.raises(BackstopUnreachableError):
            await verify_credential("bob.smith", "token", _BASE_URL)

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_unreachable_on_network_error(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(side_effect=httpx.ConnectError("boom"))

        with pytest.raises(BackstopUnreachableError):
            await verify_credential("bob.smith", "token", _BASE_URL)

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_basic_auth_and_token_header(self) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(200))

        await verify_credential("bob.smith", "p@55W0rd321!", _BASE_URL)

        assert route.called
        sent_request = route.calls.last.request
        assert sent_request.headers["authorization"] == _BASIC_AUTH
        assert sent_request.headers["token"] == "true"
