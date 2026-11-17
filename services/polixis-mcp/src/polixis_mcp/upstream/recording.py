"""Record Polixis's answers once and replay them, so the MCP can be developed and tested without
spending the API key's quota. For local development only: the recordings are licensed data
about real people, and `main` refuses either mode unless sign-in is off.
"""

import asyncio
from datetime import datetime
from datetime import UTC
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import time
from typing import ClassVar, override

import httpx2
from mcp_configs import shared_config
from mcp_openapi.upstream import UpstreamError
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import JsonValue
from pydantic import model_validator
from pydantic import TypeAdapter
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from polixis_mcp.upstream.quota import is_quota_spent


class RecordingMode(StrEnum):
    OFF = "off"
    # Answer from a saved answer where there is one; send the others and save their answers.
    # Delete a recording to have it asked again.
    RECORD = "record"
    # Answer from the saved answers and send nothing.
    REPLAY = "replay"


class RecordingSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("UPSTREAM_RECORDING_")

    mode: RecordingMode = RecordingMode.OFF
    directory: Path = Path(".mock-server-data/cassettes")
    # The most requests the ledger may hold across every recording run. Required to record.
    budget: int | None = Field(default=None, ge=0)
    # The least time between two requests sent to Polixis, across the process.
    min_interval_seconds: float = Field(default=2, ge=0)

    @model_validator(mode="after")
    def _budget_to_record(self) -> RecordingSettings:
        assert self.mode is not RecordingMode.RECORD or self.budget is not None, (
            "UPSTREAM_RECORDING_BUDGET is required to record"
        )
        return self


class CassetteMissingError(UpstreamError):
    """Replay found no saved answer for a request. An `UpstreamError`, so the agent reads why
    the tool failed instead of a masked error, and stops trying other arguments.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class RecordingRefusedError(UpstreamError):
    """Record mode did not send a request: the budget is spent or a quota 429 halted it."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class CassetteTransport(httpx2.AsyncBaseTransport):
    """Records or replays the API's requests. The token request never reaches it, so no secret
    is ever written: see `token_transport`.
    """

    def __init__(
        self, settings: RecordingSettings, inner: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        assert settings.mode is not RecordingMode.OFF
        self._settings: RecordingSettings = settings
        self._inner: httpx2.AsyncBaseTransport = inner or httpx2.AsyncHTTPTransport()
        self._directory: Path = settings.directory
        self._lock: asyncio.Lock = asyncio.Lock()
        self._last_sent: float = 0.0
        self._directory.mkdir(parents=True, exist_ok=True)

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        key = await _request_key(request)
        cassette = self._directory / f"{key.name}.json"
        if self._settings.mode is RecordingMode.REPLAY or cassette.exists():
            return _replayed(cassette, key)
        return await self._record(request, key, cassette)

    @override
    async def aclose(self) -> None:
        await self._inner.aclose()

    async def _record(
        self, request: httpx2.Request, key: _RequestKey, cassette: Path
    ) -> httpx2.Response:
        async with self._lock:
            # The same request may have waited here while another recorded it.
            if cassette.exists():
                return _replayed(cassette, key)
            self._refuse_unless_allowed(key)
            wait = self._last_sent + self._settings.min_interval_seconds - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_sent = time.monotonic()
            try:
                response = await self._inner.handle_async_request(request)
                content = await response.aread()
                await response.aclose()
            except BaseException:
                # Polixis may have counted it although no answer came back.
                self._append_ledger(key, None, None)
                raise
            spent = is_quota_spent(response)
            # A throttled or unavailable answer says nothing about the request, so it is not
            # replayed; the next run asks again.
            saved = not spent and response.status_code not in _TRANSIENT_STATUSES
            self._append_ledger(key, response.status_code, cassette.name if saved else None)
            if spent:
                (self._directory / _HALT).write_text(
                    f"Polixis answered a quota 429 at {_now()}. Delete this file to record again.\n"
                )
            elif saved:
                _save(cassette, key, response=response, content=content)
        # `content` is decoded already, so the headers that describe the encoded body go.
        headers = [
            (name, value)
            for name, value in response.headers.multi_items()
            if name.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
        ]
        return httpx2.Response(
            response.status_code, headers=headers, content=content, request=request
        )

    def _refuse_unless_allowed(self, key: _RequestKey) -> None:
        halt = self._directory / _HALT
        if halt.exists():
            raise RecordingRefusedError(
                f"{key.method} {key.path} not sent: {halt.read_text().strip()}"
            )
        sent = ledger_count(self._directory)
        budget = self._settings.budget
        assert budget is not None
        if sent >= budget:
            raise RecordingRefusedError(
                f"{key.method} {key.path} not sent: the ledger holds {sent} requests, the "
                f"budget is {budget}. Raise UPSTREAM_RECORDING_BUDGET to send more."
            )

    def _append_ledger(self, key: _RequestKey, status: int | None, cassette: str | None) -> None:
        line = {
            "at": _now(),
            "method": key.method,
            "path": key.path,
            "status": status,
            "cassette": cassette,
        }
        with (self._directory / _LEDGER).open("a") as ledger:
            ledger.write(json.dumps(line) + "\n")


def token_transport(settings: RecordingSettings) -> httpx2.AsyncBaseTransport | None:
    """What the client-credentials token is fetched over: Polixis itself when recording, so the
    secret it posts is never saved, and a made-up token when replaying.
    """
    if settings.mode is RecordingMode.REPLAY:
        return httpx2.MockTransport(
            lambda _request: httpx2.Response(
                200, json={"access_token": "replayed", "expires_in": 3600}
            )
        )
    return None


def ledger_count(directory: Path) -> int:
    """The requests sent to Polixis by every recording run into `directory`."""
    ledger = directory / _LEDGER
    if not ledger.exists():
        return 0
    with ledger.open() as lines:
        return sum(1 for line in lines if line.strip())


class _RequestKey(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    method: str
    path: str
    query: str
    body: JsonValue

    @property
    def name(self) -> str:
        """The cassette's file name: readable, and unique to the request."""
        canonical = json.dumps(
            [self.method, self.path, self.query, self.body], sort_keys=True, ensure_ascii=False
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        return f"{self.method.lower()}_{self.path.strip('/').replace('/', '_')}_{digest}"


async def _request_key(request: httpx2.Request) -> _RequestKey:
    content = await request.aread()
    body: JsonValue = None
    if content:
        try:
            body = _JSON.validate_json(content)
        except ValueError:
            body = content.decode(errors="replace")
    query = "&".join(sorted(f"{k}={v}" for k, v in request.url.params.multi_items()))
    return _RequestKey(method=request.method, path=request.url.path, query=query, body=body)


class _SavedResponse(BaseModel):
    status: int
    is_json: bool
    body: JsonValue


class _Cassette(BaseModel):
    recorded_at: str
    request: _RequestKey
    response: _SavedResponse


def _save(cassette: Path, key: _RequestKey, *, response: httpx2.Response, content: bytes) -> None:
    try:
        body: JsonValue = _JSON.validate_json(content) if content else None
        is_json = True
    except ValueError:
        body, is_json = content.decode(errors="replace"), False
    saved = _Cassette(
        recorded_at=_now(),
        request=key,
        response=_SavedResponse(status=response.status_code, is_json=is_json, body=body),
    )
    cassette.write_text(saved.model_dump_json(indent=1))


def _replayed(cassette: Path, key: _RequestKey) -> httpx2.Response:
    if not cassette.exists():
        raise CassetteMissingError(
            "This MCP is replaying recorded Polixis answers, and has no recording of this "
            f"request: {key.method} {key.path}?{key.query} body={key.body!r}. Only calls "
            "recorded before answer; others fail the same way, so do not retry with other "
            "arguments. Tell the user which call has no recording."
        )
    saved = _Cassette.model_validate_json(cassette.read_text()).response
    if saved.is_json:
        return httpx2.Response(saved.status, json=saved.body)
    return httpx2.Response(saved.status, text=str(saved.body or ""))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_LEDGER = "ledger.jsonl"
_TRANSIENT_STATUSES = frozenset({429, 503})
_HALT = "HALT"
