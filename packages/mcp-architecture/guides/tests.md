# Tests

- Answer the upstream from `tests/conftest.py` through `httpx2.MockTransport`, and call each
  tool through a real FastMCP `Client`. With the first tool, add a `call_tool` fixture to
  `tests/conftest.py` that does this, as the demo's does. Test tools this way, end to end
  through the context to the fake upstream.
- CI runs no Postgres or Redis. `create_server` takes the function that opens the persistence,
  so `open_fake_persistence` in `tests/offline_server.py` opens SQLite through `aiosqlite` and a
  `MemoryStore` in their place, for the `persistence` fixture in `tests/conftest.py`. That is why
  `Store` is typed as the `AsyncKeyValue` protocol. SQLite is not Postgres: a test that needs
  Postgres behaviour, such as a timezone or a JSON column, needs a real database.
- `tests/test_server.py` covers the ops routes, the host and origin guard, CORS and the refusal
  to serve beyond loopback without auth, through the MCP's own `http_app` and `run_server`.
- A custom upstream's `tests/test_upstream.py` covers its client: the parse into the model, the
  auth header and each retry rule, against `httpx2.MockTransport`.
- `uv run mcp-architecture-check` runs the checks of what a client sees against the server
  `offline_server()` in `tests/offline_server.py` builds: the descriptions, the input schemas,
  the masked errors and the settings that keep their input out of an error. It runs outside
  pytest, for the reason [`CUSTOM_CHECKS.md`](../CUSTOM_CHECKS.md) gives. The `server` fixture
  builds the same server with `build_server`.
- One of them compares every tool the server lists, its arguments, output, annotations and
  tags, with `tests/tool_surface.generated.json`. A change to what a client sees is a diff of
  that file in review. Accept a change you meant with `uv run mcp-architecture-check --update`.
- Tests import through the top level too.
