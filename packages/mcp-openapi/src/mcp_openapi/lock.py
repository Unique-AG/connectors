from contextlib import AbstractAsyncContextManager
from typing import ClassVar, Protocol, runtime_checkable

import httpx2
from pydantic import BaseModel, ConfigDict, Field


@runtime_checkable
class RequestLock(Protocol):
    def hold(self, request: httpx2.Request, /) -> AbstractAsyncContextManager[None]:
        """Held around each attempt of `request`, and released while a retry waits.

        `request` carries the method, URL, query, body and the client's default headers, so a
        lock can be keyed on any of them, such as the `Authorization` header. Headers that an
        event hook sets are not on it yet. Entering is cancelled when it outlasts the timeout of
        its `LockPolicy`, so it must not leave the lock taken when that happens.
        """
        ...


class LockPolicy(BaseModel):
    """A `RequestLock` and how long a request waits to acquire it before failing."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    lock: RequestLock
    acquire_timeout_seconds: float = Field(gt=0)
