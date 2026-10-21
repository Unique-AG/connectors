# persistence

Storage the MCP owns: Postgres, Redis, a key-value store. [`ARCHITECTURE.md`](../ARCHITECTURE.md)
holds the rules this guide works within, and the names every `persistence/__init__.py` exports.

Empty when the MCP stores nothing. Otherwise an MCP owns one or more stores, and `Persistence`
holds each of them as a field, so adding a store later changes no existing caller.
`persistence/persistence.py` defines `Persistence`, `PersistenceSettings` and
`open_persistence`, which opens every store in the server lifespan.

- **Postgres.** `persistence.database` is an `async_sessionmaker`:
  `async with persistence.database() as session`. Models subclass `persistence.Base` in
  `persistence/models.py`. `uv run alembic revision --autogenerate -m "<what changed>"` writes a
  migration into `persistence/migrations/versions/` and runs ruff over it, so it keeps the code
  style. The chart's migration hook runs `alembic upgrade head` before each rollout. The base
  chart injects `DATABASE_URL`.
- **Redis.** `persistence.store` is a `py-key-value-aio` `RedisStore`, typed as the
  `AsyncKeyValue` protocol, with `get`, `put`, `delete` and a TTL per entry. `StoreSettings` is
  `mcp_configs.RedisSettings`, set by `REDIS_URL`.

Contexts depend on what is stored, never on SQLAlchemy or Redis directly. Expose functions or
models from `persistence/__init__.py` that say what they store, such as
`persistence/positions.py` and `persistence/price_cache.py`.
