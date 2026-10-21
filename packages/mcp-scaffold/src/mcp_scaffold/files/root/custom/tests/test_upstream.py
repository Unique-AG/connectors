from mcp_configs import RetrySettings
import httpx2
from pydantic import BaseModel
from pydantic import TypeAdapter
import pytest

from mcp_skeleton.upstream import open_upstream
from mcp_skeleton.upstream import UpstreamError
from mcp_skeleton.upstream import UpstreamSettings


class Thing(BaseModel):
    name: str


THING = TypeAdapter(Thing)


class Answers:
    """Answers each request with the next status, and keeps every request it got."""

    def __init__(
        self, *statuses: int, headers: dict[str, str] | None = None, body: object = None
    ) -> None:
        self.statuses: list[int] = list(statuses)
        self.headers: dict[str, str] = headers or {}
        self.body: object = {"name": "anvil"} if body is None else body
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.statuses.pop(0), headers=self.headers, json=self.body)


async def request(
    settings: UpstreamSettings, answers: Answers, method: str = "GET", path: str = "/things"
) -> Thing:
    async with open_upstream(settings, httpx2.MockTransport(answers)) as upstream:
        return await upstream.request(method, path, THING)


@pytest.fixture
def settings(upstream_settings: UpstreamSettings) -> UpstreamSettings:
    """Three attempts that never sleep, whatever the fake upstream settings say."""
    retry = RetrySettings(max_attempts=3, max_wait_seconds=0, statuses=frozenset({429, 503}))
    return upstream_settings.model_copy(update={"retry": retry})


async def test_parses_the_body_into_the_model(settings: UpstreamSettings) -> None:
    assert await request(settings, Answers(200)) == Thing(name="anvil")


async def test_sends_the_api_key_as_a_bearer_token(settings: UpstreamSettings) -> None:
    answers = Answers(200)

    await request(settings, answers)

    assert answers.requests[0].headers["Authorization"] == "Bearer dummy-api-key"


async def test_retries_a_rate_limit_until_it_succeeds(settings: UpstreamSettings) -> None:
    answers = Answers(429, 503, 200)

    assert await request(settings, answers) == Thing(name="anvil")
    assert len(answers.requests) == 3


async def test_gives_up_after_the_last_attempt(settings: UpstreamSettings) -> None:
    answers = Answers(503, 503, 503)

    with pytest.raises(UpstreamError, match="503 Service Unavailable for GET"):
        await request(settings, answers)
    assert len(answers.requests) == 3


async def test_does_not_retry_a_client_error(settings: UpstreamSettings) -> None:
    answers = Answers(404)

    with pytest.raises(UpstreamError, match="404 Not Found"):
        await request(settings, answers)
    assert len(answers.requests) == 1


async def test_does_not_wait_longer_than_the_retry_settings_allow(
    settings: UpstreamSettings,
) -> None:
    answers = Answers(429, headers={"Retry-After": "3600"})

    with pytest.raises(UpstreamError, match="429"):
        await request(settings, answers)
    assert len(answers.requests) == 1


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_does_not_resend_a_write_that_may_have_been_applied(
    settings: UpstreamSettings, method: str
) -> None:
    answers = Answers(503)

    with pytest.raises(UpstreamError, match="503"):
        await request(settings, answers, method)
    assert len(answers.requests) == 1


async def test_logs_the_error_body_but_does_not_return_it(
    settings: UpstreamSettings, caplog: pytest.LogCaptureFixture
) -> None:
    answers = Answers(404, body={"detail": "internal"})

    with pytest.raises(UpstreamError) as error:
        await request(settings, answers)

    assert str(error.value) == "404 Not Found for GET https://api.example.com/things"
    assert [record.getMessage() for record in caplog.records] == [
        '404 Not Found for GET https://api.example.com/things: {"detail":"internal"}'
    ]


async def test_resends_the_body_of_a_rate_limited_write(settings: UpstreamSettings) -> None:
    answers = Answers(429, 200)

    async with open_upstream(settings, httpx2.MockTransport(answers)) as upstream:
        await upstream.request("POST", "/things", THING, json={"name": "anvil"})

    assert [sent.read() for sent in answers.requests] == [b'{"name":"anvil"}'] * 2


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
async def test_resends_an_idempotent_write_on_an_unavailable_upstream(
    settings: UpstreamSettings, method: str
) -> None:
    answers = Answers(503, 200)

    assert await request(settings, answers, method) == Thing(name="anvil")
    assert len(answers.requests) == 2


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_resends_any_write_the_upstream_rate_limited(
    settings: UpstreamSettings, method: str
) -> None:
    answers = Answers(429, 200)

    assert await request(settings, answers, method) == Thing(name="anvil")
    assert len(answers.requests) == 2


async def test_a_body_that_does_not_fit_the_model_is_an_upstream_error(
    settings: UpstreamSettings,
) -> None:
    with pytest.raises(UpstreamError, match="Unexpected response: name: Field required"):
        await request(settings, Answers(200, body={"title": "anvil"}))


async def test_refuses_anything_but_a_path(settings: UpstreamSettings) -> None:
    with pytest.raises(ValueError, match="is not a path"):
        await request(settings, Answers(200), path="https://elsewhere.example.com/things")
