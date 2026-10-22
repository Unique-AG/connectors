from collections.abc import Callable, Coroutine, Iterable, Mapping
from typing import cast

import httpx2

_TRANSPORT_HEADERS = frozenset({"host", "content-length", "content-type", "transfer-encoding"})


def only_headers(
    allowed: frozenset[str], fixed: Mapping[str, str], *, origin: str
) -> Callable[[httpx2.Request], Coroutine[object, object, None]]:
    """An httpx request hook that drops every header not in `allowed`, then sets `fixed`.

    The headers a request cannot be sent without are always kept. `fixed` is only set on
    requests to `origin`, so no other host, scheme or port gets it.
    """
    allowed = frozenset(name.lower() for name in allowed) | _TRANSPORT_HEADERS
    base = httpx2.URL(origin)

    async def hook(request: httpx2.Request) -> None:
        for name in {
            key for key in cast(Iterable[str], request.headers) if key.lower() not in allowed
        }:
            del request.headers[name]
        url = request.url
        if (url.scheme, url.host, url.port) == (base.scheme, base.host, base.port):
            request.headers.update(fixed)

    return hook
