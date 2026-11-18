from typing import Protocol

from pydantic import AwareDatetime
from pydantic import BaseModel


class CachedAnswer(BaseModel):
    """A Polixis answer as the cache holds it: its body as Polixis sent it, and when it was
    cached.
    """

    cached_at: AwareDatetime
    body: bytes


class ResponseCache(Protocol):
    """Where the upstream client keeps Polixis's answers, which persistence implements."""

    async def get(self, key: str) -> CachedAnswer | None:
        """None when nothing unexpired is cached under `key`. A hit counts as a use of it, so
        the least recently used answers are the first to go when the cache is full.
        """
        ...

    async def put(self, key: str, answer: CachedAnswer, *, ttl_seconds: int) -> None: ...
