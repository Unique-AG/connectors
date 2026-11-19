import hashlib
import os
import time
from collections.abc import Callable
from typing import override

from mcp.server.request_state import (
    AESGCMRequestStateCodec,
    InvalidRequestState,
    RequestStateCodec,
    RequestStateSecurity,
)

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
        now = self._clock()
        while self._spent and next(iter(self._spent.values())) <= now:
            del self._spent[next(iter(self._spent))]
        key = hashlib.sha256(token.encode()).digest()
        if key in self._spent:
            raise InvalidRequestState("replayed")
        self._spent[key] = now + self._remembered_for
        return payload


def request_state_security() -> RequestStateSecurity:
    sealing = AESGCMRequestStateCodec([os.urandom(32)])
    return RequestStateSecurity(
        codec=SingleUseRequestState(
            sealing, remembered_for=_LIFETIME_SECONDS + _CLOCK_SKEW_SECONDS
        ),
        ttl=_LIFETIME_SECONDS,
    )
