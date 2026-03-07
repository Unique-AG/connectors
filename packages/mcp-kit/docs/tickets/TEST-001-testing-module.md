# TEST-001: McpTestingModule

## Summary
Create `McpTestingModule` — a test harness that builds a full NestJS `TestingModule` with the MCP framework wired up, but without HTTP transport. Uses `InMemoryTransport.createLinkedPair()` from the SDK to connect a test client directly to the server. Provides ergonomic APIs for tool testing with full DI, mock auth, and provider overrides.

## Background / Context
Testing MCP tools today requires either spinning up an HTTP server or manually constructing SDK objects. `McpTestingModule` eliminates this boilerplate by providing a pattern similar to `@nestjs/testing`'s `Test.createTestingModule()`, but purpose-built for MCP:

- Full NestJS DI (tools get their real injected services, or mocks via `overrideProviders`)
- No network — `InMemoryTransport.createLinkedPair()` connects client and server in-process
- `testModule.client` is a `McpTestClient` (TEST-002) for ergonomic assertions
- `testModule.withAuth()` sets mock identity for subsequent calls
- `testModule.close()` cleans everything up

This lives in a separate package: `@unique-ag/nestjs-mcp-testing`.

## Acceptance Criteria
- [ ] `McpTestingModule.create(options)` is an async static factory method
- [ ] Options:
  - `imports: Type[]` — NestJS modules to import (includes the module under test)
  - `overrideProviders?: { provide: InjectionToken, useValue | useClass | useFactory }[]` — provider overrides (mocks)
- [ ] Internally builds a `TestingModule` via `Test.createTestingModule()` with `McpModule` auto-imported
- [ ] Uses `InMemoryTransport.createLinkedPair()` to create linked server + client transports
- [ ] `testModule.client` returns a `McpTestClient` instance (TEST-002)
- [ ] `testModule.withAuth(identity: Partial<McpIdentity>)` sets mock identity that will be visible via `ctx.identity` in tool handlers
  - Merges provided fields with sensible defaults (e.g., `userId: 'test-user'`, `scopes: []`)
  - Can be called multiple times to change identity between test cases
- [ ] `testModule.resetAuth()` clears mock identity (tools see `isAuthenticated: false`)
- [ ] `testModule.close()` disconnects transports, closes the NestJS app, cleans up
- [ ] The testing module uses `InMemorySessionStore` regardless of what the imported modules configure
- [ ] Pipeline (guards, interceptors, pipes) runs normally in tests — no special bypass

## BDD Scenarios

```gherkin
Feature: MCP testing module
  A test harness that wires up the full NestJS MCP framework
  with in-memory transport for fast, isolated tool testing.

  Rule: Tools execute with full dependency injection

    Scenario: Tool uses real injected services by default
      Given a testing module created with the EmailModule imported
      When the test calls tool "search_email" with query: "hello"
      Then the tool executes with the real EmailService dependency
      And the tool result is returned

    Scenario: Provider overrides replace real services with mocks
      Given a testing module created with the EmailModule imported
      And EmailService overridden with a mock implementation
      When the test calls tool "search_email" with query: "hello"
      Then the tool executes with the mock EmailService
      And the mock's behavior is observed in the result

  Rule: Mock authentication controls identity in tool handlers

    Scenario: Setting mock auth makes tools see the configured identity
      Given a testing module with a tool "get_profile" that reads user identity
      When mock auth is set to userId "user-123" with scopes ["mail.read"]
      And the test calls tool "get_profile"
      Then the tool sees userId "user-123" and scopes ["mail.read"]
      And the request is treated as authenticated

    Scenario: Resetting auth makes tools see unauthenticated state
      Given a testing module with mock auth previously configured
      When mock auth is reset
      And the test calls tool "public_tool"
      Then the tool sees the request as unauthenticated

  Rule: Guards and interceptors run normally in tests

    Scenario: Scope guard blocks unauthorized tool calls
      Given a testing module with a tool "search_email" that requires scope "mail.read"
      When mock auth is set to userId "user-1" with no scopes
      And the test calls tool "search_email"
      Then the call is rejected with an authorization error

  Rule: Testing modules are isolated from each other

    Scenario: Concurrent test suites have independent state
      Given test suite A creates a testing module with userId "user-a"
      And test suite B creates a testing module with userId "user-b"
      When both suites call tool "get_profile" concurrently
      Then suite A's tool sees userId "user-a"
      And suite B's tool sees userId "user-b"

  Rule: Cleanup releases all resources

    Scenario: Closing the testing module disconnects everything
      Given a testing module with an active client connection
      When the testing module is closed
      Then the in-memory transport is disconnected
      And the NestJS application is shut down

  Rule: Advanced MCP features work through in-memory transport

    Scenario: Elicitation round-trips work in tests
      Given a testing module with a tool "interactive_tool" that collects user input via elicitation
      When the test calls tool "interactive_tool"
      Then the elicitation request and response are handled via in-memory transport
```

## Dependencies
- **Depends on:** TEST-002 (McpTestClient) — exposed as `testModule.client`
- **Depends on:** CORE-012 (McpModule.forRoot) — testing module auto-imports McpModule with test-appropriate defaults
- **Depends on:** TRANS-001/002/003 — testing module needs awareness of transport types (uses InMemoryTransport instead)
- **Blocks:** none

## Technical Notes
- Package: `@unique-ag/nestjs-mcp-testing` (separate package, like `@nestjs/testing`)
- File location: `packages/nestjs-mcp-testing/src/mcp-testing-module.ts`
- `InMemoryTransport.createLinkedPair()` from `@modelcontextprotocol/sdk/inMemory.js` returns `[clientTransport, serverTransport]`. The server transport connects to the McpServer; the client transport connects to the SDK `Client`.
- `withAuth()` implementation: override the `McpIdentityResolver` provider to return a fixed `McpIdentity`. Since the testing module controls the DI container, this can use `testingModule.overrideProvider(McpIdentityResolver).useValue(mockResolver)`. However, since the module is already compiled, a simpler approach is to have a `MockIdentityResolver` registered at creation time that reads from a mutable ref: `testModule.withAuth()` sets the ref, `MockIdentityResolver.resolve()` reads it.
- The `McpModule` import should be auto-configured with `InMemorySessionStore` and STDIO-like transport (no HTTP routes needed).
- Ensure the `McpServer` in the test module has all tools/resources/prompts registered from the imported modules.
- `create()` should call `app.init()` but NOT `app.listen()` (no HTTP server).
