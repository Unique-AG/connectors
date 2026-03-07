# CORE-024: getMcpContext() — context access from nested services

## Summary
Implement `getMcpContext()` utility function that retrieves the current `McpContext` from anywhere in the call stack during an MCP request, using Node.js `AsyncLocalStorage` for propagation without parameter threading.

## Background / Context
FastMCP v2.2.11+ provides `get_context()` — a function callable from anywhere in the call stack during an MCP request, not just from the handler with `ctx: Context` parameter. This uses Python's `ContextVar` to propagate the context implicitly through the async call stack.

In NestJS, tool/resource/prompt handlers access context via `@Ctx()` parameter injection. However, services nested deep in the call stack (e.g., a `DatabaseService` called by an `EmailService` called by a tool handler) don't have access to `McpContext` unless it's explicitly passed through every function signature. This ticket solves that by using Node.js `AsyncLocalStorage` to store the `McpContext` for the duration of each MCP request and exposing a `getMcpContext()` function to retrieve it.

## Acceptance Criteria
- [ ] `McpContextStorage` — singleton class wrapping `AsyncLocalStorage<McpContext>` instance
- [ ] `getMcpContext(): McpContext | null` — exported function from `@unique-ag/nestjs-mcp` that returns the current MCP context or `null` if called outside an MCP request
- [ ] `requireMcpContext(): McpContext` — exported function that returns the current MCP context or throws `Error('No MCP context available. This function must be called within an MCP request handler.')` if called outside a request
- [ ] MCP handlers (CORE-013) wrap each tool/resource/prompt invocation in `McpContextStorage.run(ctx, handler)` so the context is propagated through the async call stack
- [ ] Context is isolated per concurrent request — two simultaneous tool calls each have their own `McpContext`
- [ ] `getMcpContext()` works from any depth in the call stack: tool handler -> service A -> service B -> utility function
- [ ] `getMcpContext()` returns `null` (not throws) when called from non-MCP code paths (e.g., a cron job, a REST endpoint)
- [ ] `McpContextStorage` is registered as a NestJS provider (singleton) for testability and DI
- [ ] `AsyncLocalStorage` instance is created once at module load time (not per request)

## BDD Scenarios

```gherkin
Feature: getMcpContext() utility for nested service access
  Services deep in the call stack can access the current MCP request
  context without requiring it to be passed through every function signature.

  Background:
    Given an MCP server is running with the nestjs-mcp module

  Rule: Context is accessible from any depth in the call stack during an MCP request

    Scenario: A nested service accesses context during tool execution
      Given a tool "send_email" calls an EmailService
      And the EmailService internally retrieves the MCP context
      When a client calls "send_email"
      Then the EmailService receives the current MCP context
      And the context contains the tool name "send_email"
      And the context contains the authenticated user's identity

    Scenario: Context is accessible three service layers deep
      Given a tool "process_order" calls OrderService
      And OrderService calls PaymentService
      And PaymentService retrieves the MCP context
      When a client calls "process_order"
      Then PaymentService receives the same context as the tool handler
      And it can read the session ID and request ID

    Scenario: Context is accessible from resource and prompt handlers
      Given a resource handler for "config://app" calls a ConfigService
      And the ConfigService retrieves the MCP context
      When a client reads the resource "config://app"
      Then the ConfigService receives a context indicating a resource operation

  Rule: Context is safely unavailable outside MCP requests

    Scenario: Retrieving context outside an MCP request returns null
      Given a scheduled background job retrieves the MCP context using the safe variant
      When the background job executes outside any MCP request
      Then the result is null

    Scenario: Requiring context outside an MCP request throws a descriptive error
      Given a REST endpoint handler requires the MCP context using the strict variant
      When the REST endpoint is called
      Then an error is thrown with a message indicating no MCP context is available

  Rule: Concurrent MCP requests have isolated contexts

    Scenario: Two simultaneous tool calls each see their own context
      Given a tool "lookup" calls a shared SearchService
      And the SearchService retrieves the MCP context
      When client A calls "lookup" with session "session-A"
      And client B calls "lookup" with session "session-B" at the same time
      Then the SearchService in client A's request sees session "session-A"
      And the SearchService in client B's request sees session "session-B"

  Rule: Context propagates through asynchronous operations

    Scenario: Context survives async operations like database queries
      Given a tool "fetch_data" starts an asynchronous database query
      And the query callback retrieves the MCP context
      When a client calls "fetch_data"
      And the async database query completes
      Then the callback receives the correct MCP context for that request
```

## FastMCP Parity
- **FastMCP**: `get_context()` — uses Python `ContextVar` to propagate context through the call stack. Returns `Context` or raises `LookupError` if called outside a request.
- **NestJS**: `getMcpContext()` / `requireMcpContext()` — uses Node.js `AsyncLocalStorage` (equivalent to Python's `ContextVar`). `getMcpContext()` returns `null` instead of throwing (safer for dual-use code). `requireMcpContext()` throws for code that must run within MCP context.
- **Difference**: We provide both a safe (`getMcpContext`) and an assertive (`requireMcpContext`) variant. FastMCP only provides the assertive variant.

## Dependencies
- **Depends on:** CORE-007 — McpContext class (the stored/retrieved type)
- **Depends on:** CORE-013 — MCP handlers (must wrap invocations in `McpContextStorage.run()`)
- **Blocks:** nothing

## Technical Notes
- `McpContextStorage` implementation:
  ```typescript
  import { AsyncLocalStorage } from 'node:async_hooks';
  import { Injectable } from '@nestjs/common';
  import type { McpContext } from '../context/mcp-context';

  @Injectable()
  export class McpContextStorage {
    private readonly storage = new AsyncLocalStorage<McpContext>();

    run<T>(context: McpContext, fn: () => T): T {
      return this.storage.run(context, fn);
    }

    getContext(): McpContext | null {
      return this.storage.getStore() ?? null;
    }
  }
  ```
- Standalone functions (for convenience):
  ```typescript
  // Singleton instance accessible without DI
  let storageInstance: McpContextStorage;

  export function getMcpContext(): McpContext | null {
    return storageInstance?.getContext() ?? null;
  }

  export function requireMcpContext(): McpContext {
    const ctx = getMcpContext();
    if (!ctx) throw new Error('No MCP context available. This function must be called within an MCP request handler.');
    return ctx;
  }
  ```
- The `McpContextStorage` provider sets the module-level `storageInstance` in its constructor so the standalone functions work without DI injection.
- Integration with CORE-013: In each handler (tools, resources, prompts), wrap the pipeline execution:
  ```typescript
  // In McpToolsHandler.callTool()
  const result = await this.contextStorage.run(ctx, () =>
    this.pipelineRunner.execute(handlerEntry, args, ctx)
  );
  ```
- `AsyncLocalStorage` has negligible performance overhead in Node.js 16+ (it's used internally by many Node.js frameworks).
- File locations:
  - `packages/nestjs-mcp/src/context/mcp-context-storage.ts` — storage class
  - `packages/nestjs-mcp/src/context/get-mcp-context.ts` — standalone utility functions
