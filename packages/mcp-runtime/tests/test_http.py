import httpx2

from mcp_runtime import RetryingTransport, RetrySettings


class Answers:
    """Answers each request with the next status, and counts the requests."""

    def __init__(self, *statuses: int, headers: dict[str, str] | None = None) -> None:
        self.statuses: list[int] = list(statuses)
        self.headers: dict[str, str] = headers or {}
        self.requests: int = 0

    def __call__(self, _request: httpx2.Request) -> httpx2.Response:
        self.requests += 1
        return httpx2.Response(self.statuses.pop(0), headers=self.headers, json={})


async def status_of_a_get(answers: Answers, max_wait_seconds: float = 0) -> int:
    retry = RetrySettings(max_attempts=3, max_wait_seconds=max_wait_seconds)
    transport = RetryingTransport(httpx2.MockTransport(answers), retry)
    async with httpx2.AsyncClient(base_url="https://api.example.com", transport=transport) as http:
        return (await http.get("/things")).status_code


async def test_retries_a_rate_limit_until_it_succeeds() -> None:
    answers = Answers(429, 503, 200)

    assert await status_of_a_get(answers) == 200
    assert answers.requests == 3


async def test_gives_up_after_the_last_attempt() -> None:
    answers = Answers(503, 503, 503)

    assert await status_of_a_get(answers) == 503
    assert answers.requests == 3


async def test_does_not_retry_a_client_error() -> None:
    answers = Answers(404)

    assert await status_of_a_get(answers) == 404
    assert answers.requests == 1


async def test_does_not_wait_longer_than_the_retry_settings_allow() -> None:
    answers = Answers(429, headers={"Retry-After": "3600"})

    assert await status_of_a_get(answers, max_wait_seconds=30) == 429
    assert answers.requests == 1
