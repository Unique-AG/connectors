from typing import override

from key_value.aio.stores.memory import MemoryStore
from pydantic import TypeAdapter

from world_check_mcp.persistence import Cache

_ADAPTER = TypeAdapter(list[str])


class _BrokenStore(MemoryStore):
    @override
    async def get(self, key: str, *, collection: str | None = None, **_: object) -> None:
        raise ConnectionError("database is down")


class _Counter:
    loads: int

    def __init__(self) -> None:
        self.loads = 0

    async def load(self) -> list[str]:
        self.loads += 1
        return ["a", "b"]


async def test_a_cached_value_is_loaded_once() -> None:
    store = MemoryStore()
    counter = _Counter()

    first = await Cache(store).read_through(
        key="k", adapter=_ADAPTER, ttl_seconds=60, load=counter.load
    )
    second = await Cache(store).read_through(
        key="k", adapter=_ADAPTER, ttl_seconds=60, load=counter.load
    )

    assert first == second == ["a", "b"]
    assert counter.loads == 1


async def test_a_value_that_no_longer_validates_is_loaded_again() -> None:
    store = MemoryStore()
    await store.put("k", {"value": {"not": "a list"}}, collection="cache")
    counter = _Counter()

    value = await Cache(store).read_through(
        key="k", adapter=_ADAPTER, ttl_seconds=60, load=counter.load
    )

    assert value == ["a", "b"]
    assert counter.loads == 1


async def test_a_store_that_cannot_be_read_still_gives_the_loaded_value() -> None:
    counter = _Counter()

    value = await Cache(_BrokenStore()).read_through(
        key="k", adapter=_ADAPTER, ttl_seconds=60, load=counter.load
    )

    assert value == ["a", "b"]


_MAP = TypeAdapter(dict[str, str])


async def test_a_cached_value_is_stored_as_a_json_string_that_postgres_cannot_reorder() -> None:
    store = MemoryStore()

    async def load() -> dict[str, str]:
        return {"ZZ": "last", "B": "first", "AAA": "middle"}

    await Cache(store).read_through(key="k", adapter=_MAP, ttl_seconds=60, load=load)

    stored = await store.get("k", collection="cache")
    assert stored is not None
    assert isinstance(stored["value"], str)


async def test_a_cached_map_keeps_the_order_lseg_sent_it_in() -> None:
    cache = Cache(MemoryStore())

    async def load() -> dict[str, str]:
        return {"ZZ": "last", "B": "first", "AAA": "middle"}

    await cache.read_through(key="k", adapter=_MAP, ttl_seconds=60, load=load)
    cached = await cache.read_through(key="k", adapter=_MAP, ttl_seconds=60, load=load)

    assert list(cached) == ["ZZ", "B", "AAA"]
