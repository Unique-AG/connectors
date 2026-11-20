import hashlib
import os
import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import override

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.server.request_state import (
    AESGCMRequestStateCodec,
    InvalidRequestState,
    RequestStateCodec,
    RequestStateSecurity,
)
from mcp.types import CallToolRequestParams

_LIFETIME_SECONDS = 600.0
_CLOCK_SKEW_SECONDS = 60.0


class SingleUseRequestState(RequestStateCodec):
    def __init__(
        self,
        codec: RequestStateCodec,
        *,
        remembered_for: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._codec: RequestStateCodec = codec
        self._remembered_for: float = remembered_for
        self._clock: Callable[[], float] = clock
        self._spent: dict[bytes, float] = {}

    @override
    def seal(self, payload: bytes) -> str:
        return self._codec.seal(payload)

    @override
    def unseal(self, token: str) -> bytes:
        payload = self._codec.unseal(token)
        self._refuse_spent(_key(token))
        _ = _UNSEALED.set((self, token))
        return payload

    def spend(self, token: str) -> None:
        key = _key(token)
        self._refuse_spent(key)
        self._spent[key] = self._clock() + self._remembered_for

    def _refuse_spent(self, key: bytes) -> None:
        now = self._clock()
        while self._spent and next(iter(self._spent.values())) <= now:
            del self._spent[next(iter(self._spent))]
        if key in self._spent:
            raise InvalidRequestState("replayed")


def _key(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


_UNSEALED: ContextVar[tuple[SingleUseRequestState, str] | None] = ContextVar(
    "office_365_mcp_unsealed_request_state", default=None
)


class SpendAnsweredState(Middleware):
    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        unsealed = _UNSEALED.get()
        _ = _UNSEALED.set(None)
        if unsealed is not None and context.message.request_state is not None:
            codec, token = unsealed
            try:
                codec.spend(token)
            except InvalidRequestState as replayed:
                raise ToolError(
                    "This answer was already used. Ask the question again."
                ) from replayed
        return await call_next(context)


def request_state_security() -> RequestStateSecurity:
    sealing = AESGCMRequestStateCodec([os.urandom(32)])
    return RequestStateSecurity(
        codec=SingleUseRequestState(
            sealing, remembered_for=_LIFETIME_SECONDS + _CLOCK_SKEW_SECONDS
        ),
        ttl=_LIFETIME_SECONDS,
    )
