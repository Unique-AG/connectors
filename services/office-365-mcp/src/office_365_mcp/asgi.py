"""The five ASGI types, spelled so that a read off a scope is not an `Any`.

Local aliases rather than Starlette's: `starlette/types.py:12-18` spells `Scope` and `Message` as
`MutableMapping[str, Any]`, so every read off one is an `Any` this service's type checking rejects.
`unique_toolkit`'s own tracing middleware keeps the same local aliases for the same reason
(`unique_toolkit/monitoring/tracing.py:18-22`).

Its own module because two middlewares need them — `logging.py` mints an HTTP request id,
`tracing.py` captures the trace context — and a type alias declared twice is two things that can
drift. Nothing of this package is imported here, so anything may import it.
"""

from collections.abc import Awaitable, Callable, MutableMapping

__all__ = ["ASGIApp", "ASGIMessage", "ASGIReceive", "ASGIScope", "ASGISend"]

type ASGIScope = MutableMapping[str, object]
type ASGIMessage = MutableMapping[str, object]
type ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
type ASGISend = Callable[[ASGIMessage], Awaitable[None]]
type ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]
