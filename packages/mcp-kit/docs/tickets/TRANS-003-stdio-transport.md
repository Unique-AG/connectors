# TRANS-003: STDIO transport service

## Summary
Build `McpStdioService` for the framework. Process stdin/stdout based transport for CLI usage. Single session, no authentication, no session store interaction. This is the simplest transport -- it connects an `McpServer` to `StdioServerTransport` on application bootstrap.

## Background / Context
The STDIO transport is used for local CLI tools (e.g., `npx my-mcp-server`). There is exactly one session, no HTTP, no auth, and no need for session persistence. The service creates a single `McpServer` and `StdioServerTransport`, connects them, and registers handlers via `McpExecutorService` with `identity: null`.

## Acceptance Criteria
- [ ] `McpStdioService` implements `OnApplicationBootstrap`
- [ ] Only activates when the configured transport list includes STDIO (e.g., `transports: ['stdio']`)
- [ ] Creates a single `McpServer` and `StdioServerTransport`
- [ ] Connects them and registers handlers via `McpExecutorService`
- [ ] Passes `null` for identity (no auth in STDIO mode)
- [ ] Does NOT interact with `McpSessionStore` or `McpSessionService`
- [ ] Does NOT register in `McpSessionRegistry`
- [ ] Logs "MCP STDIO transport ready" on successful bootstrap
- [ ] If transport list does not include STDIO, `onApplicationBootstrap()` returns immediately without creating any transport

## BDD Scenarios

```gherkin
Feature: STDIO transport
  The simplest MCP transport for local CLI usage. Uses process stdin/stdout
  for communication. Supports a single unauthenticated session with no
  persistence or session management.

  Rule: Bootstrap behavior depends on configured transports

    Scenario: The STDIO transport starts when included in the transport list
      Given an MCP server configured with transports: ["stdio"]
      When the application starts
      Then tool call requests received via stdin produce responses on stdout
      And "MCP STDIO transport ready" is logged

    Scenario: The STDIO transport does not start when not in the transport list
      Given an MCP server configured with transports: ["streamable-http"]
      When the application starts
      Then no STDIO transport is created
      And no STDIO-related log messages are emitted

    Scenario: STDIO and HTTP transports can run simultaneously
      Given an MCP server configured with transports: ["streamable-http", "stdio"]
      When the application starts
      Then both the STDIO and HTTP transports are active
      And tool calls work independently on each transport

  Rule: STDIO sessions are unauthenticated and untracked

    Scenario: All STDIO tool calls are unauthenticated
      Given an active STDIO transport
      When a tool call is received via stdin
      Then the tool handler receives an unauthenticated context
      And no session is persisted in the session store

    Scenario: No session management is used for STDIO
      Given an active STDIO transport
      When tool calls are received and processed
      Then the session store is never accessed
      And the session registry is never accessed

  Rule: Bootstrap errors are handled gracefully

    Scenario: A startup failure is logged without crashing the application
      Given an MCP server configured with transports: ["stdio"]
      And the STDIO transport cannot be created due to an error
      When the application starts
      Then the error is logged
      And the application continues running
```

## Dependencies
- Depends on: CORE-012 -- `McpModule` configuration (transport list)
- Blocks: TEST-001 (McpTestingModule)

## Technical Notes
- File location: `packages/nestjs-mcp/src/transport/stdio.service.ts`
- SDK APIs used:
  - `StdioServerTransport` from `@modelcontextprotocol/sdk/server/stdio.js` -- reads from `process.stdin`, writes to `process.stdout`
  - `McpServer` from `@modelcontextprotocol/sdk/server/mcp.js` -- created once
  - `McpServer.connect(transport)` -- links server to transport
- Transport type check: check `this.options.transports?.includes('stdio')` or equivalent. The framework may support multiple transports simultaneously.
- No pipeline changes needed -- STDIO tools go through the same pipeline runner as HTTP tools, just with `identity: null`.
- Pass `null` for identity since `McpExecutorService` accepts `McpIdentity | null`.
