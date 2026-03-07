# TRANS-002: SSE transport service (legacy, deprecated)

## Summary
Build `McpSseService` for the framework as a legacy/deprecated transport, integrating session management via `McpSessionService` and identity resolution via `McpIdentityResolver`. Registers `GET /sse` (stream) and `POST /message` (messages) routes. Clearly marked as deprecated in favor of Streamable HTTP (TRANS-001).

## Background / Context
The SSE transport (`GET /sse` + `POST /message`) is the legacy MCP transport. The MCP spec deprecates it in favor of Streamable HTTP, but many existing clients still use it. The framework supports it for backwards compatibility while clearly marking it as deprecated.

The service delegates session lifecycle to `McpSessionService`, resolves identity via `McpIdentityResolver`, and integrates with the ping service for connection keepalive.

Session resumption (SESS-006) does NOT apply to SSE. SSE connections are inherently lost on disconnect -- clients must establish a new `/sse` connection. Old session records remain in the store until they expire.

## Acceptance Criteria
- [ ] `McpSseController` (a standard `@Controller()` class) exposes two routes: `@Get('/sse')` and `@Post('/message')`
- [ ] Route paths configurable via `McpModule.forRoot({ sse: { ssePath, messagePath } })`
- [ ] `GET /sse`: creates SSE connection, creates `SSEServerTransport` and `McpServer`, calls `McpSessionService.registerSession()` with transportType `"sse"`
- [ ] `POST /message`: looks up session by `sessionId` query param, routes to existing transport, calls `transport.handlePostMessage()`
- [ ] `POST /message` calls `McpSessionService.touchSession()` on each message (fire-and-forget)
- [ ] Transport `onclose` triggers `McpSessionService.unregisterSession()`
- [ ] Ping service integration: register connections on SSE open, remove on close
- [ ] Class and all route methods are annotated with `/** @deprecated Use Streamable HTTP transport instead */` JSDoc
- [ ] A deprecation warning is logged once on service initialization (`onModuleInit`)
- [ ] `McpIdentityResolver` is resolved per request for identity resolution
- [ ] `POST /message` with missing `sessionId` query param returns 400
- [ ] `POST /message` for unknown session returns 404

## BDD Scenarios

```gherkin
Feature: SSE transport (legacy, deprecated)
  The legacy MCP transport using separate GET /sse and POST /message
  endpoints. Maintained for backwards compatibility with older clients.
  Session resumption is not supported -- clients must reconnect with
  a new SSE stream after disconnection.

  Rule: Establishing an SSE connection and session

    Background:
      Given an MCP server with SSE transport enabled

    Scenario: A client establishes an SSE connection and a session is created
      When a client sends GET /sse
      Then an SSE stream is opened with Content-Type "text/event-stream"
      And a new session is registered with transport type "sse"
      And the client receives the message endpoint URL for sending requests

    Scenario: A deprecation warning is logged when the SSE transport starts
      When the SSE transport service initializes
      Then a warning is logged: "SSE transport is deprecated. Use Streamable HTTP transport instead."
      And the warning is logged only once, not per connection

  Rule: Routing messages to active sessions

    Scenario: A message is routed to the correct SSE session
      Given client "client-a" has an active SSE session "sess-1"
      When a POST request arrives at /message with session ID "sess-1" and a tool call
      Then the tool call is processed by session "sess-1"
      And the session's activity time is updated
      And the response is sent back via the SSE stream

    Scenario: A message to a non-existent session returns 404
      When a POST request arrives at /message with session ID "nonexistent"
      Then a 404 response is returned

    Scenario: A message without a session ID parameter returns 400
      When a POST request arrives at /message without a session ID parameter
      Then a 400 response is returned with error "Missing sessionId parameter"

    Scenario: An activity tracking failure does not block message handling
      Given client "client-a" has an active SSE session "sess-1"
      And the session store is temporarily unavailable
      When a POST request arrives at /message with session ID "sess-1"
      Then the message is still processed successfully
      And a warning is logged about the activity tracking failure

  Rule: Cleanup on disconnect

    Scenario: A disconnected client's session is removed and its keepalive stopped
      Given client "client-a" has an active SSE session "sess-1"
      When the client's SSE connection closes
      Then the session is removed from active tracking and from the store
      And the keepalive ping for that connection is stopped

  Rule: Transport configuration

    Scenario: The SSE and message paths are configurable
      Given an MCP server configured with SSE path "/api/sse" and message path "/api/message"
      When a client sends GET /api/sse
      Then an SSE stream is opened
      And GET /sse returns 404
```

## Dependencies
- Depends on: SESS-005 -- session registration wiring pattern
- Depends on: SESS-004 -- `McpSessionService`
- Blocks: TEST-001 (McpTestingModule)

## Technical Notes
- File location: `packages/nestjs-mcp/src/transport/sse.service.ts`
- The `SSEServerTransport` from SDK takes the message endpoint URL and raw response in its constructor.
- SDK APIs used:
  - `SSEServerTransport` from `@modelcontextprotocol/sdk/server/sse.js` -- handles SSE stream + message routing
  - `SSEServerTransport.handlePostMessage(req, res)` -- processes incoming POST messages
  - `McpServer` from `@modelcontextprotocol/sdk/server/mcp.js` -- created per SSE connection
  - `McpServer.connect(transport)` -- links server to transport
- The ping service (`SsePingService`) sends periodic SSE comments to keep connections alive through proxies. Register connections on SSE open, remove on close.
- Route registration uses a standard `@Controller()` class (`McpSseController`) — enables standard NestJS guards/interceptors/pipes on SSE endpoints
- Identity resolution in the `/message` POST handler: resolve `McpIdentityResolver` per request, same as Streamable HTTP.
- Deprecation: use `/** @deprecated Use Streamable HTTP transport instead */` JSDoc on the class and exported symbols.
- Session resumption does NOT apply to SSE -- SSE connections are stateful HTTP streams that cannot be resumed after disconnect.
