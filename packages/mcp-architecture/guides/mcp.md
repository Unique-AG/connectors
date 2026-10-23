# mcp

The FastMCP server, its HTTP serving and middleware, auth, tools and their inputs and responses.
[`ARCHITECTURE.md`](../ARCHITECTURE.md) holds the rules this guide works within.

- `server.py`: `create_server` builds the FastMCP app. Its lifespan opens the upstream and the
  persistence, and the tools receive them through `Depends(get_upstream)` and
  `Depends(get_persistence)` from `dependencies.py`.
- `http.py`: `run_server` serves the app over streamable HTTP at `/mcp`, stateless, and
  `http_app` serves the same app to the tests. `run_server` refuses to bind beyond loopback
  while the server has no auth provider, `FastMCP(auth=...)`, so an MCP without auth runs
  locally but never in a pod.
- `middleware.py`: `http_middleware` puts the host and origin guard first, then CORS, then the
  MCP's own HTTP middleware, such as a request id, after `instrument(mcp)`. The guard lets a
  request through only for the host of `MCP_BASE_URL` (`localhost` and `127.0.0.1` alike when
  that is local) and, from a browser, an allowed origin. `/probe`, `/health` and `/metrics` skip it, since Kubernetes and Prometheus
  reach the pod by IP. MCP-level middleware, which sees tool calls rather than HTTP requests,
  goes on the server in `create_server`: `mcp.add_middleware(...)`.
- `auth/`, once the MCP has auth: what FastMCP does not provide itself, behind its own
  `__init__.py`. With `--auth credentials` it is the OAuth server the clients use and its
  `/sign-in` page (see [auth](auth.md)).
- `tools/`: `FileSystemProvider` discovers every `@tool` under it. A new tool file is picked up
  with no registration step. If one fails to import, the server refuses to start.

## Tools

- A tool starts as one file, `tools/get_price_performance.py`. It becomes a folder when its
  inputs or responses grow past about ten lines:

  ```
  mcp/tools/record_position/
  ├── __init__.py
  ├── record_position.py             the @tool
  ├── record_position_inputs.py      Annotated parameter types
  └── record_position_responses.py   only if the tool reshapes what the context returns
  ```

  The demo's `record_position` has no responses file, since it returns the context's
  `PortfolioValuation` as it is.

- An input or response several tools share goes in `mcp/inputs/<name>.py` or
  `mcp/responses/<name>.py`, as `Ticker` does in `mcp/inputs/ticker.py`.
- A tool is thin. It turns parameters into the context's input, calls one context function,
  and turns the context's errors into `ToolError`. It holds no business rule.
- Every parameter is `Annotated[..., Field(description=...)]`. The description and the
  docstring are what the model reads, so say when to call the tool and what its ids feed into.
- Set `ToolAnnotations` honestly. A tool that orders, pays or deletes is not read-only, and one
  that deletes or overwrites is destructive: the MCP spec keeps `destructiveHint=false` for a
  tool that only adds. `record_position` replaces a holding's quantity and cost basis, so it is
  destructive, and idempotent, since recording the same holding twice changes nothing more.
- Return the context's model unless the tool needs another shape.
