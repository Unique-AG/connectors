# TRANS-001: Streamable HTTP transport service

## Summary
Build `McpStreamableHttpService` for the framework, integrating session management (via `McpSessionService`), identity resolution (via `McpIdentityResolver`), and the NestJS pipeline. Registers `POST /mcp`, `GET /mcp`, and `DELETE /mcp` routes. Supports both stateful (session-tracked) and stateless (per-request) modes. This is the primary transport -- the modern replacement for SSE.

## Background / Context
Streamable HTTP is the recommended MCP transport (the MCP spec deprecates SSE in its favor). It uses a single endpoint path for all operations:
- `POST` for JSON-RPC requests (initialize, tool calls, etc.)
- `GET` for server-to-client SSE notification stream
- `DELETE` for session termination

The service manages session lifecycle by delegating to `McpSessionService` (SESS-004), resolves user identity via `McpIdentityResolver` (CORE-006), and integrates session resumption (SESS-006) for zero-downtime deployments.

Session state is managed by `McpSessionService` instead of local objects. Identity is resolved via `McpIdentityResolver` (not raw `request.user`). Metrics are handled by `MetricsInterceptor` (pipeline) instead of manual counters.

## Acceptance Criteria
- [ ] `McpStreamableHttpController` (a standard `@Controller('mcp')` class) exposes three routes: `@Post('/mcp')`, `@Get('/mcp')`, `@Delete('/mcp')`
- [ ] Route paths are configurable via `McpModule.forRoot({ streamableHttp: { path: '/mcp' } })`
- [ ] **Stateful mode** (default):
  - [ ] POST without `Mcp-Session-Id` + initialize method: creates new session, generates session ID, returns it in `Mcp-Session-Id` response header
  - [ ] POST with valid `Mcp-Session-Id`: routes to existing session, touches session
  - [ ] POST with unknown `Mcp-Session-Id`: attempts resumption (SESS-006 logic), falls back to 404
  - [ ] GET with valid `Mcp-Session-Id`: establishes SSE stream for server-to-client notifications
  - [ ] GET without or with invalid `Mcp-Session-Id`: returns 400
  - [ ] DELETE with valid `Mcp-Session-Id`: terminates session via `McpSessionService.terminateSession()`
  - [ ] DELETE with unknown `Mcp-Session-Id`: returns 404
- [ ] **Stateless mode** (`statelessMode: true`):
  - [ ] Each POST creates a fresh transport + McpServer, handles request, cleans up
  - [ ] GET and DELETE return 405
  - [ ] No session store interaction
- [ ] `McpIdentityResolver` is resolved once per request and identity is passed to `McpExecutorService`
- [ ] `McpSessionService.registerSession()` is called on new session initialization (SESS-005 pattern)
- [ ] `McpSessionService.touchSession()` is called on every request to existing session (fire-and-forget)
- [ ] Transport `onclose` triggers `McpSessionService.unregisterSession()`
- [ ] Session ID generator is configurable via `streamableHttp.sessionIdGenerator`
- [ ] `enableJsonResponse` option is forwarded to SDK transport
- [ ] Express HTTP adapter is used (Fastify support deferred)

## BDD Scenarios

```gherkin
Feature: Streamable HTTP transport
  The primary MCP transport using a single HTTP endpoint for all
  operations. Supports stateful (session-tracked) and stateless
  (per-request) modes with session resumption for zero-downtime
  deployments.

  Rule: Stateful mode -- session lifecycle via POST, GET, DELETE

    Background:
      Given an MCP server with Streamable HTTP transport in stateful mode at path "/mcp"

    Scenario: An initialize request creates a new session
      When a client sends POST /mcp with an initialize request and no session ID header
      Then the response includes a new session ID in the Mcp-Session-Id header
      And the session is registered with transport type "streamable-http"
      And the initialize response is returned in the body

    Scenario: A subsequent request is routed to the existing session
      Given client "client-a" has an active session "sess-1"
      When the client sends POST /mcp with a tool call and Mcp-Session-Id "sess-1"
      Then the tool call is processed by the existing session
      And the session's activity is updated
      And the tool call response is returned

    Scenario: A request with a persisted but not locally tracked session ID triggers resumption
      Given session "sess-1" exists in the store but the server has restarted
      When a client sends POST /mcp with Mcp-Session-Id "sess-1" authenticated as the session owner
      Then the session is resumed and the request is handled

    Scenario: A request with a completely unknown session ID returns 404
      When a client sends POST /mcp with Mcp-Session-Id "nonexistent"
      Then a 404 response is returned with error "Session not found"

    Scenario: A GET request opens an SSE notification stream for an active session
      Given client "client-a" has an active session "sess-1"
      When the client sends GET /mcp with Mcp-Session-Id "sess-1"
      Then an SSE stream is opened with Content-Type "text/event-stream"

    Scenario: A GET request without a session ID returns 400
      When a client sends GET /mcp without a Mcp-Session-Id header
      Then a 400 response is returned

    Scenario: A DELETE request terminates the session
      Given client "client-a" has an active session "sess-1"
      When the client sends DELETE /mcp with Mcp-Session-Id "sess-1"
      Then the session is terminated and the connection is closed
      And a 200 response is returned

    Scenario: A DELETE request for an unknown session returns 404
      When a client sends DELETE /mcp with Mcp-Session-Id "nonexistent"
      Then a 404 response is returned

  Rule: Stateless mode -- each request is independent

    Background:
      Given an MCP server with Streamable HTTP transport in stateless mode

    Scenario: Each POST request is handled independently without session tracking
      When a client sends POST /mcp with an initialize and tool call
      Then the request is handled with a fresh server instance
      And no session is persisted

    Scenario: GET requests are not supported in stateless mode
      When a client sends GET /mcp
      Then a 405 Method Not Allowed response is returned

    Scenario: DELETE requests are not supported in stateless mode
      When a client sends DELETE /mcp
      Then a 405 Method Not Allowed response is returned

  Rule: Transport configuration

    Scenario: The endpoint path is configurable
      Given an MCP server configured with Streamable HTTP path "/api/mcp"
      When a client sends POST /api/mcp with an initialize request
      Then the request is handled successfully
      And POST /mcp returns 404

    Scenario: A custom session ID generator is used for new sessions
      Given an MCP server configured with a session ID generator that returns "custom-123"
      When a client sends an initialize request
      Then the session ID "custom-123" is returned in the response header
```

## Dependencies
- Depends on: SESS-006 -- session resumption logic
- Depends on: SESS-005 -- session registration wiring pattern
- Depends on: SESS-004 -- `McpSessionService` and `McpSessionRegistry`
- Blocks: TEST-001 (McpTestingModule)

## Technical Notes
- File location: `packages/nestjs-mcp/src/transport/streamable-http.service.ts`
- Route registration uses a standard `@Controller('mcp')` class (`McpStreamableHttpController`) — this enables `@UseGuards()`, `@UseInterceptors()`, `@UsePipes()` on MCP HTTP endpoints natively
- REQUEST-scoped providers (e.g. `McpIdentityResolver`) are resolved automatically by NestJS DI when injected into a REQUEST-scoped controller or service — no manual `moduleRef.resolve()` needed
- SDK APIs used:
  - `StreamableHTTPServerTransport` from `@modelcontextprotocol/sdk/server/streamableHttp.js` -- handles JSON-RPC framing, SSE streaming, session ID headers
  - `StreamableHTTPServerTransport.handleRequest(req, res)` -- delegates HTTP handling to the SDK
  - `StreamableHTTPServerTransport.onsessioninitialized` -- callback for new session creation
  - `McpServer` from `@modelcontextprotocol/sdk/server/mcp.js` -- created per session
  - `McpServer.connect(transport)` -- links server to transport
- The `HttpAdapterFactory` pattern for Express compatibility should be used. Fastify support is deferred.
- No manual `requestCounter` metric -- handled by `MetricsInterceptor` in the pipeline.
