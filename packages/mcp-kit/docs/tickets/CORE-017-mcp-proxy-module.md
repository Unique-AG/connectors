# CORE-017: McpProxyModule — MCP Client Bridge (create_proxy equivalent)

## Summary
`McpProxyModule` embeds an MCP SDK `Client` and re-exposes the remote server's tools, resources, and prompts as if they were local NestJS components. Enables transport bridging, multi-server aggregation, security gateways, and stdio subprocess proxying. This is the NestJS equivalent of FastMCP's `create_proxy()`.

## Background / Context
FastMCP (Python) provides `create_proxy()` to bridge one MCP server into another:
- `create_proxy(url)` — full MCP client bridge to a remote HTTP MCP server
- `create_proxy("file.py")` — bridge to a stdio subprocess
- `create_proxy({ mcpServers: { weather: {url: "..."}, calendar: {url: "..."} } })` — aggregate multiple servers with auto-namespacing

This is useful for:
- **Security gateways**: expose curated subsets of upstream servers behind auth
- **Transport bridging**: expose an stdio MCP server over HTTP
- **Server aggregation**: combine multiple upstream MCP servers into one unified interface
- **Development**: proxy remote MCP servers locally for testing

Proxied components are "read-through" — they reflect the remote server's state live. The proxy does not modify or cache upstream component definitions by default.

## Acceptance Criteria

### Single upstream server
- [ ] `McpProxyModule.forRoot({ name: 'weather', upstream: { url: 'https://weather-api.example.com/mcp' } })` connects to a remote MCP server
- [ ] All upstream tools are registered as local tools in the handler registry
- [ ] All upstream resources are registered as local resources
- [ ] All upstream prompts are registered as local prompts
- [ ] Tool call on a proxied tool forwards the call to the upstream server and returns the response
- [ ] `listTools` reflects the current upstream tool list (fetched from upstream or cached with short TTL)
- [ ] `listResources` and `listPrompts` similarly reflect upstream state

### Multiple upstream servers (aggregation)
- [ ] `McpProxyModule.forRoot({ upstream: [{ name: 'weather', url: '...' }, { name: 'calendar', url: '...' }] })` connects to multiple servers
- [ ] Each upstream server's components are auto-namespaced by server name: `weather_get_forecast`, `calendar_add_event`
- [ ] No name collisions between upstream servers thanks to auto-namespacing

### Stdio subprocess upstream
- [ ] `McpProxyModule.forRoot({ upstream: { command: 'uvx', args: ['some-mcp-server'] } })` spawns a subprocess
- [ ] Communication with subprocess is via stdin/stdout using MCP stdio transport
- [ ] Subprocess lifecycle is managed by the module (spawned on init, killed on destroy)

### Claude Desktop / mcpServers config format
- [ ] `McpProxyModule.forRoot({ upstream: { mcpServers: { weather: { url: '...' }, calendar: { command: 'npx', args: ['...'] } } } })` supports mixed config
- [ ] Each entry in `mcpServers` creates a namespaced upstream client (same as multi-upstream mode)

### Optional prefix / namespacing
- [ ] `McpProxyModule.forRoot({ upstream: { url: '...' }, prefix: 'weather' })` applies prefix to all proxied components
- [ ] Prefix rules follow CORE-016: tools `{prefix}_{name}`, resources `protocol://{prefix}/path`, prompts `{prefix}-{name}`

### NpxStdioTransport and UvxStdioTransport
- [ ] `NpxStdioTransport`: `{ upstream: { npxPackage: 'package-name', args?: string[], env?: Record<string, string> } }` — spawns `npx -y package-name` as stdio subprocess
- [ ] `UvxStdioTransport`: `{ upstream: { uvxTool: 'tool-name', args?: string[], env?: Record<string, string> } }` — spawns `uvx tool-name` as stdio subprocess
- [ ] `env` option on any subprocess transport passes environment variables to the spawned process
- [ ] Upstream server configuration uses a discriminated union `McpUpstreamConfig` to prevent invalid combinations:
  ```typescript
  type McpUpstreamConfig =
    | { kind: 'http';  url: string; headers?: Record<string, string>; timeout?: number }
    | { kind: 'stdio'; command: string; args?: string[]; env?: Record<string, string> }
    | { kind: 'npx';   package: string; args?: string[]; version?: string }
    | { kind: 'uvx';   tool: string; args?: string[] };
  ```
  A single interface with all fields optional is not permitted — `kind` is required and narrows the type.

### Session mode
- [ ] `sessionMode: 'isolated'` (default) — each incoming request creates a fresh upstream client connection; prevents context mixing between concurrent downstream clients
- [ ] `sessionMode: 'shared'` — single upstream client reused across all requests; faster (no reconnect overhead) but may mix context in concurrent scenarios

### Session isolation
- [ ] Each incoming MCP request spawns a fresh upstream client call (no shared backend session state between different downstream clients)
- [ ] Upstream client connections are pooled per upstream server (not per downstream session) for efficiency

### Authentication
- [ ] Optional `forwardAuth: true` config forwards the caller's bearer token to the upstream server
- [ ] Optional `upstreamAuth: { token: '...' }` provides a static token for upstream authentication
- [ ] Optional `upstreamAuth: { tokenFactory: () => Promise<string> }` provides dynamic token resolution

### Subprocess timeout
- [ ] If a subprocess tool call does not return within `subprocessTimeoutMs` (default: 30000ms, configurable), the proxy throws `McpError(RequestTimeout)`. The subprocess is NOT killed on timeout — it continues running and may complete later

### Error handling
- [ ] Upstream server unavailable → tool call returns `{ isError: true, content: [{ type: 'text', text: 'Upstream server unavailable: ...' }] }`
- [ ] Upstream timeout → tool call returns `{ isError: true }` with descriptive timeout message
- [ ] Individual upstream failure in multi-server mode does not prevent other upstreams from functioning

### Multi-server partial failure
- [ ] If one upstream in a multi-server config is unavailable at list time, its tools/resources/prompts are omitted from the response with a warning log. The server does NOT fail entirely
- [ ] At call time, if the specific upstream is unavailable, the call returns an error result

## BDD Scenarios

```gherkin
Feature: MCP Proxy Module
  The proxy module embeds an MCP client and re-exposes a remote server's
  tools, resources, and prompts as local components, enabling transport
  bridging, multi-server aggregation, and security gateways.

  Rule: Single upstream server proxying

    Scenario: Upstream tools appear in the local tool list and are callable
      Given a proxy configured to connect to a remote weather MCP server
      And the upstream server exposes tool "get_forecast" accepting a "location" parameter
      When a client requests the tool list
      Then "get_forecast" appears with the upstream's parameter schema
      When a client calls "get_forecast" with location "Zurich"
      Then the call is forwarded to the upstream server
      And the upstream response is returned to the client

    Scenario: Tool call arguments are forwarded verbatim to upstream
      Given a proxied tool "search" from an upstream server
      When a client calls "search" with query "test"
      Then the upstream receives a call to "search" with query "test"
      And the upstream response is returned unchanged

  Rule: Multi-server aggregation

    Scenario: Multiple upstream servers are auto-namespaced to avoid collisions
      Given a proxy configured with upstream servers "weather" and "calendar"
      And the weather server exposes tool "get_forecast"
      And the calendar server exposes tool "add_event"
      When a client requests the tool list
      Then "weather_get_forecast" and "calendar_add_event" appear
      And there are no name collisions

    Scenario: Mixed transport config with mcpServers format
      Given a proxy configured with an HTTP upstream named "weather" and a subprocess upstream named "local_tool"
      When a client requests the tool list
      Then tools from both upstreams appear namespaced by their server names

  Rule: Stdio subprocess upstream

    Scenario: Subprocess is spawned on startup and cleaned up on shutdown
      Given a proxy configured to run "uvx weather-mcp" as a subprocess
      When the application starts
      Then a subprocess is spawned
      And tools from the subprocess appear in the tool list
      When the application shuts down
      Then the subprocess is terminated gracefully

    Scenario: Npx package subprocess is spawned and callable
      Given a proxy configured with an npx package "weather-mcp-server" and args "--port 3000"
      When the application starts and a tool is called
      Then a subprocess running the npx package is spawned
      And tools from the subprocess are available

    Scenario: Uvx tool subprocess receives environment variables
      Given a proxy configured with a uvx tool "weather-mcp" and environment variable API_KEY "secret"
      When the application starts and a tool is called
      Then the subprocess is spawned with API_KEY set to "secret"
      And tools from the subprocess are available

  Rule: Error handling

    Scenario: Unavailable upstream returns an error response
      Given a proxy configured to connect to an unresponsive upstream server
      When a client calls a proxied tool
      Then the client receives an error response indicating the upstream is unavailable
      And no unhandled exception propagates

  Rule: Prefix namespacing for proxied components

    Scenario: Prefix is applied to all proxied component names
      Given a proxy configured with prefix "ext" and an upstream exposing tool "search", resource "data://items", and prompt "summarize"
      When a client requests the tool, resource, and prompt lists
      Then the tool appears as "ext_search"
      And the resource appears as "data://ext/items"
      And the prompt appears as "ext-summarize"

  Rule: Multi-server partial failure

    Scenario: Unavailable upstream is omitted from list responses
      Given a proxy configured with upstream servers "weather" and "calendar"
      And the weather server is unavailable
      When a client requests the tool list
      Then tools from "calendar" still appear
      And a warning is logged about the weather server being unavailable

    Scenario: Call to unavailable upstream returns an error
      Given a proxy configured with upstream servers "weather" and "calendar"
      And the weather server is unavailable
      When a client calls "weather_get_forecast"
      Then the client receives an error response indicating the upstream is unavailable

  Rule: Subprocess timeout

    Scenario: Subprocess tool call that exceeds timeout returns an error
      Given a proxy configured with a subprocess upstream and a timeout of 5000ms
      And the subprocess tool takes longer than 5000ms to respond
      When a client calls the proxied tool
      Then the client receives a timeout error
      And the subprocess continues running

  Rule: Authentication forwarding

    Scenario: Caller's auth token is forwarded to the upstream server
      Given a proxy configured with auth forwarding enabled
      And a downstream client sends a request with bearer token "abc123"
      When the proxy forwards a tool call to the upstream
      Then the upstream request includes the bearer token "abc123"

  Rule: Session mode

    Scenario: Shared session mode reuses a single upstream connection
      Given a proxy configured with shared session mode
      When client A calls "get_forecast" and then client B calls "get_forecast"
      Then both calls use the same upstream connection
      And no reconnection occurs between calls
```

## FastMCP Parity
FastMCP (Python) supports:
- `create_proxy(url)` — single remote server proxy (our `McpProxyModule.forRoot({ upstream: { url } })`)
- `create_proxy("file.py")` — stdio subprocess proxy (our `upstream: { command, args }`)
- `create_proxy({ mcpServers: {...} })` — multi-server aggregation (our `upstream: { mcpServers }` or `upstream: [...]`)
- Proxied components reflect remote state live (our read-through behavior)
- Feature forwarding: roots, sampling, elicitation, logging, progress (our feature forwarding)
- Session isolation: each request gets its own backend session (our session isolation)
- Performance: 200-500ms overhead per proxied call vs 1-2ms local (same expected overhead)

## Dependencies
- **Depends on:** CORE-001 (@Tool registration interface) — proxy tools register using the same interface
- **Depends on:** CORE-005 (Handler registry) — proxy tools register themselves in the central registry
- **Depends on:** CORE-013 (McpToolsHandler/ResourcesHandler/PromptsHandler) — handlers integrate proxy tools alongside local tools
- **Depends on:** SESS-004 (McpSessionService) — session context needed for proxy session management
- **Blocks:** CORE-029 (Proxy feature forwarding), CORE-030 (Proxy McpModule integration)

## Technical Notes
- Uses `@modelcontextprotocol/sdk` `Client` class internally — one `Client` instance per upstream server
- Client transport selection based on config:
  - `url` → `StreamableHTTPClientTransport` (or fallback to SSE)
  - `command` + `args` → `StdioClientTransport`
  - `npxPackage` → `StdioClientTransport` wrapping `npx -y <package>` (additional `args` appended after package name)
  - `uvxTool` → `StdioClientTransport` wrapping `uvx <tool>` (additional `args` appended after tool name)
  - `env` → merged with `process.env` and passed to `child_process.spawn()` for any subprocess transport
- **Lazy connection**: upstream clients connect on first use, not at module init (avoids startup failures if upstream is temporarily down)
- **Reconnection**: built-in reconnection logic with exponential backoff for HTTP upstreams
- **List caching**: upstream `listTools`/`listResources`/`listPrompts` results are cached with a configurable TTL (default: 30s). Cache is invalidated on upstream `list_changed` notifications if the upstream supports them.
- **Registration pattern**: proxied tools are registered with the `McpRegistryService` as special `ProxyRegistryEntry` entries that hold a reference to the upstream client. When the handler invokes a proxied tool, it delegates to the upstream client's `callTool()` method.
- **File locations**:
  - `packages/nestjs-mcp/src/proxy/mcp-proxy.module.ts`
  - `packages/nestjs-mcp/src/proxy/proxy-client.service.ts`
  - `packages/nestjs-mcp/src/proxy/proxy-registry.service.ts`
  - `packages/nestjs-mcp/src/proxy/interfaces.ts`
- **Performance**: expect 200-500ms overhead per proxied tool call (network round-trip to upstream). List operations hit upstream on every request unless cached. Deep proxy hierarchies (proxy of proxy) compound latency — document this limitation.
- **Subprocess management**: stdio upstreams use Node.js `child_process.spawn()`. The module manages the subprocess lifecycle: spawn on `onModuleInit`, kill on `onModuleDestroy`. Handle SIGTERM gracefully.
- **Session mode**: `sessionMode: 'isolated'` (default) creates a fresh upstream client connection per incoming request, preventing context mixing between concurrent downstream clients. `sessionMode: 'shared'` reuses a single upstream client across all requests for lower latency but potential context mixing. In `shared` mode, the upstream client is established once on first use and reused until module destruction.
- **Config interface**:
  ```typescript
  type McpUpstreamConfig =
    | { kind: 'http';  url: string; headers?: Record<string, string>; timeout?: number }
    | { kind: 'stdio'; command: string; args?: string[]; env?: Record<string, string> }
    | { kind: 'npx';   package: string; args?: string[]; version?: string }
    | { kind: 'uvx';   tool: string; args?: string[] };

  interface McpProxyModuleOptions {
    name?: string;
    upstream: McpUpstreamConfig | McpUpstreamConfig[] | { mcpServers: Record<string, McpUpstreamConfig> };
    prefix?: string;
    forwardAuth?: boolean;
    upstreamAuth?: { token: string } | { tokenFactory: () => Promise<string> };
    listCacheTtlMs?: number; // default: 30_000
    sessionMode?: 'isolated' | 'shared'; // default: 'isolated'
    subprocessTimeoutMs?: number; // default: 30_000 — timeout for subprocess tool calls
  }
  ```
