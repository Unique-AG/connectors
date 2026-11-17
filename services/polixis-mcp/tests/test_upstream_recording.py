import asyncio
import gzip
import json
from pathlib import Path

from fastmcp import Client
import httpx2
import pytest

from polixis_mcp.mcp import create_server
from polixis_mcp.upstream.recording import CassetteMissingError
from polixis_mcp.upstream.recording import CassetteTransport
from polixis_mcp.upstream.recording import ledger_count
from polixis_mcp.upstream.recording import RecordingMode
from polixis_mcp.upstream.recording import RecordingRefusedError
from polixis_mcp.upstream.recording import RecordingSettings
from polixis_mcp.upstream.settings import UpstreamSettings
from tests.offline_server import fake_upstream_settings
from tests.offline_server import open_fake_persistence
from tests.tool_calls import tool_error

API = "https://api.example.com"
PROFILE = {"pid": "O00000000000000000000000000000100", "name": "Kestrel Marine Services Ltd"}


def polixis(sent: list[httpx2.Request], response: httpx2.Response) -> httpx2.MockTransport:
    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return response

    return httpx2.MockTransport(answer)


def settings(directory: Path, mode: RecordingMode, budget: int | None = 10) -> RecordingSettings:
    return RecordingSettings(mode=mode, directory=directory, budget=budget, min_interval_seconds=0)


async def post(transport: httpx2.AsyncBaseTransport, body: dict[str, object]) -> httpx2.Response:
    async with httpx2.AsyncClient(base_url=API, transport=transport) as http:
        return await http.post("/api/completion/O1", json=body, params={"lang": "en"})


async def test_replays_what_it_recorded(tmp_path: Path) -> None:
    sent: list[httpx2.Request] = []
    recorder = CassetteTransport(
        settings(tmp_path, RecordingMode.RECORD),
        polixis(sent, httpx2.Response(200, json=PROFILE)),
    )
    recorded = await post(recorder, {"fields": ["names"], "id": 1})

    replayed = await post(
        CassetteTransport(settings(tmp_path, RecordingMode.REPLAY)), {"id": 1, "fields": ["names"]}
    )

    assert (recorded.json(), replayed.json(), replayed.status_code) == (PROFILE, PROFILE, 200)
    assert len(sent) == 1
    assert ledger_count(tmp_path) == 1


async def test_replay_without_a_recording_fails(tmp_path: Path) -> None:
    with pytest.raises(
        CassetteMissingError, match="no recording of this request: POST /api/completion/O1"
    ):
        _ = await post(CassetteTransport(settings(tmp_path, RecordingMode.REPLAY)), {"id": 2})


async def test_record_sends_nothing_past_the_budget(tmp_path: Path) -> None:
    sent: list[httpx2.Request] = []
    recorder = CassetteTransport(
        settings(tmp_path, RecordingMode.RECORD, budget=1),
        polixis(sent, httpx2.Response(200, json=PROFILE)),
    )
    _ = await post(recorder, {"id": 1})

    with pytest.raises(RecordingRefusedError, match="budget is 1"):
        _ = await post(recorder, {"id": 2})
    assert len(sent) == 1


async def test_records_a_request_sent_twice_at_once_only_once(tmp_path: Path) -> None:
    sent: list[httpx2.Request] = []
    both_asked = asyncio.Barrier(2)

    async def ask(body: dict[str, object]) -> httpx2.Response:
        await both_asked.wait()
        return await post(recorder, body)

    async def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        await asyncio.sleep(0)
        return httpx2.Response(200, json=PROFILE)

    recorder = CassetteTransport(
        settings(tmp_path, RecordingMode.RECORD), httpx2.MockTransport(answer)
    )

    answers = await asyncio.gather(ask({"id": 1}), ask({"id": 1}))

    assert [answer.json() for answer in answers] == [PROFILE, PROFILE]
    assert (len(sent), ledger_count(tmp_path)) == (1, 1)


async def test_counts_a_request_that_got_no_answer_against_the_budget(tmp_path: Path) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("no answer", request=request)

    recorder = CassetteTransport(
        settings(tmp_path, RecordingMode.RECORD), httpx2.MockTransport(fail)
    )

    with pytest.raises(httpx2.ReadTimeout):
        _ = await post(recorder, {"id": 1})
    assert ledger_count(tmp_path) == 1


async def test_a_spent_quota_halts_every_later_run(tmp_path: Path) -> None:
    sent: list[httpx2.Request] = []
    spent = httpx2.Response(
        429,
        json={"message": "Limit Exceeded"},
        headers={"x-amzn-errortype": "LimitExceededException:"},
    )
    _ = await post(
        CassetteTransport(settings(tmp_path, RecordingMode.RECORD), polixis(sent, spent)), {"id": 1}
    )

    later = CassetteTransport(
        settings(tmp_path, RecordingMode.RECORD),
        polixis(sent, httpx2.Response(200, json=PROFILE)),
    )
    with pytest.raises(RecordingRefusedError, match="quota 429"):
        _ = await post(later, {"id": 2})
    assert len(sent) == 1
    assert ledger_count(tmp_path) == 1
    assert not list(tmp_path.glob("post_*.json"))


def test_recording_needs_a_budget(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="BUDGET is required"):
        _ = settings(tmp_path, RecordingMode.RECORD, budget=None)


async def test_returns_a_compressed_answer_decoded(tmp_path: Path) -> None:
    sent: list[httpx2.Request] = []
    compressed = httpx2.Response(
        200,
        content=gzip.compress(json.dumps(PROFILE).encode()),
        headers={"content-encoding": "gzip"},
    )
    recorder = CassetteTransport(
        settings(tmp_path, RecordingMode.RECORD), polixis(sent, compressed)
    )

    assert (await post(recorder, {"id": 1})).json() == PROFILE


async def test_record_answers_a_recorded_request_without_sending_it(tmp_path: Path) -> None:
    sent: list[httpx2.Request] = []
    recorder = CassetteTransport(
        settings(tmp_path, RecordingMode.RECORD), polixis(sent, httpx2.Response(200, json=PROFILE))
    )
    _ = await post(recorder, {"id": 1})

    again = await post(recorder, {"id": 1})

    assert again.json() == PROFILE
    assert len(sent) == 1
    assert ledger_count(tmp_path) == 1


@pytest.fixture
def no_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither the environment nor a `.env` gives the Polixis credentials."""
    monkeypatch.chdir(tmp_path)
    for name in ("UPSTREAM_CLIENT_ID", "UPSTREAM_CLIENT_SECRET", "UPSTREAM_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("no_credentials")
def test_replay_needs_no_polixis_credentials(tmp_path: Path) -> None:
    upstream = UpstreamSettings(recording=settings(tmp_path, RecordingMode.REPLAY))

    assert (upstream.client_id, upstream.client_secret, upstream.api_key) == (None, None, None)


@pytest.mark.usefixtures("no_credentials")
def test_record_needs_the_polixis_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UPSTREAM_CLIENT_ID, UPSTREAM_CLIENT_SECRET"):
        _ = UpstreamSettings(recording=settings(tmp_path, RecordingMode.RECORD))


async def test_a_replay_miss_reaches_the_agent_with_its_reason(tmp_path: Path) -> None:
    upstream = fake_upstream_settings().model_copy(
        update={"recording": settings(tmp_path, RecordingMode.REPLAY)}
    )
    async with Client(create_server(upstream, open_fake_persistence)) as client:
        error = await tool_error(client, "search_entities", {"name": "Kestrel Marine Services"})

    assert "has no recording of this request: POST /search/api" in error
    assert "do not retry with other arguments" in error
