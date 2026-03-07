# CORE-010: McpPipelineRunner (ExternalContextCreator integration)

## Summary
Implement `McpPipelineRunner`, the service that wires NestJS's `ExternalContextCreator` to execute the full guard/interceptor/pipe pipeline for MCP operations. This is the core integration point that makes standard NestJS `@UseGuards()`, `@UseInterceptors()`, and `@UsePipes()` decorators work for MCP tool/resource/prompt handlers, with the execution order: Zod validation -> Pipes -> Guards -> Interceptors (onion) -> Handler -> Serialization -> Error normalization.

## Background / Context
NestJS's `ExternalContextCreator` (from `@nestjs/core`) is the official extensibility hook used by `@nestjs/microservices` and `@nestjs/websockets`. It reads `__guards__`, `__interceptors__`, `__pipes__` metadata keys, collects `APP_GUARD` / `APP_INTERCEPTOR` / `APP_PIPE` providers from `ApplicationConfig`, and builds a wrapped handler function. `McpPipelineRunner` uses this mechanism so that MCP tools participate in the same pipeline as HTTP controllers.

The key difference from HTTP is that Zod validation is mandatory and always runs first (before NestJS pipes), and error normalization always catches exceptions and converts them to `{ isError: true }` MCP responses.

## Acceptance Criteria
- [ ] `McpPipelineRunner` is an `@Injectable()` singleton service
- [ ] Uses `ExternalContextCreator.fromContainer()` to create wrapped handlers
- [ ] Wrapped handlers include guards, interceptors, pipes, and exception filters from `ApplicationConfig`
- [ ] Supports `@UseGuards()`, `@UseInterceptors()`, `@UsePipes()` at class and method level
- [ ] Supports `APP_GUARD`, `APP_INTERCEPTOR`, `APP_PIPE` global providers
- [ ] Merges pipeline in order: global -> class -> method (per-tool `guards`/`interceptors` from @Tool options map to method-level)
- [ ] Zod schema validation runs FIRST, before any pipe/guard/interceptor
- [ ] If Zod validation fails, returns `McpError(InvalidParams)` immediately (no pipeline execution)
- [ ] `HttpException` thrown by guard -> `{ content: [...], isError: true }` MCP response
- [ ] `McpError` thrown anywhere -> `{ content: [...], isError: true }` MCP response (unless it's InvalidParams/MethodNotFound which should propagate as protocol errors)
- [ ] Unknown exceptions -> `{ content: [...], isError: true }` with error message
- [ ] Error normalization is always-on (not opt-in)
- [ ] The wrapped handler receives an `McpExecutionContextHost` with `contextType = 'mcp'`
- [ ] Method: `wrapHandler(registryEntry, mcpServer, identity, sessionId, httpRequest) -> (input) => Promise<ToolResult>`

## BDD Scenarios

```gherkin
Feature: MCP Pipeline Runner
  The pipeline runner wraps MCP tool handlers with the standard NestJS
  guard / interceptor / pipe chain and normalizes all errors into MCP responses.

  Background:
    Given an MCP server is running with the pipeline runner enabled

  Rule: Guards control access to tools

    Scenario: Global guard blocks an unauthenticated tool call
      Given a global authentication guard that rejects unauthenticated callers
      And a tool "search_emails" is registered
      When an unauthenticated client calls "search_emails"
      Then the tool handler is not executed
      And the client receives an error response with message "Forbidden"

    Scenario: Per-tool guard only affects the decorated tool
      Given a tool "delete_all" that requires the "admin" role
      And a tool "search" with no role restrictions
      And the current caller has role "viewer"
      When the caller invokes "delete_all"
      Then the caller receives an error response
      When the caller invokes "search"
      Then the tool executes successfully

  Rule: Interceptors wrap handler execution in onion order

    Scenario: Two global interceptors execute in registration order
      Given a logging interceptor registered before a metrics interceptor
      And a tool "search" is registered
      When a client calls "search"
      Then the logging interceptor processes the call before the metrics interceptor
      And the metrics interceptor completes post-processing before the logging interceptor

  Rule: Pipes transform validated input before the handler

    Scenario: A global pipe trims string arguments
      Given a global pipe that trims whitespace from string values
      And a tool "search" that accepts a "query" parameter
      When a client calls "search" with query "  hello  "
      Then the tool handler receives query "hello"

  Rule: Zod schema validation runs before all other pipeline steps

    Scenario: Invalid input is rejected before any pipeline component runs
      Given a tool "count_items" that requires a numeric "count" parameter
      When a client calls "count_items" with count "not a number"
      Then the client receives an InvalidParams protocol error
      And no guard, pipe, or interceptor is executed

  Rule: All exceptions are normalized into MCP error responses

    Scenario: A forbidden exception from a guard becomes an MCP error response
      Given a guard that rejects the caller with message "No access"
      When the caller invokes any tool
      Then the client receives an error response with message "No access"

    Scenario: An unexpected handler exception becomes an MCP error response
      Given a tool "risky_op" whose handler throws an unexpected error "something broke"
      When a client calls "risky_op"
      Then the client receives an error response with message "something broke"
      And the error does not propagate to the transport layer

    Scenario: A schema validation error propagates as a protocol-level error
      Given a tool with a strict numeric parameter
      When a client sends a non-numeric value for that parameter
      Then the client receives an InvalidParams protocol error
      And the error is not caught by the error normalization layer
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Depends on: CORE-005 — registry entries to wrap
- Depends on: CORE-008 — output serialization for formatting results
- Depends on: CORE-009 — McpExecutionContextHost creation
- Blocks: CORE-007 — McpContext created within pipeline
- Blocks: CORE-011 — built-in components execute within pipeline
- Blocks: CORE-012 — module wires pipeline runner

## Interface Contract
Consumed by CORE-007 (McpContext creation), CORE-013 (handlers):
```typescript
@Injectable()
export class McpPipelineRunner {
  /** Wraps a registry entry into a pipeline-executing function */
  wrapHandler(
    entry: RegistryEntry,
    mcpServer: McpServer,
    identity: McpIdentity | null,
    sessionId: string | null,
    httpRequest: HttpRequest | null,
  ): (input: Record<string, unknown>) => Promise<ToolResult>;
}
```

## Technical Notes
- Core integration pattern (from design artifact):
  ```typescript
  const externalContextCreator = ExternalContextCreator.fromContainer(nestContainer);
  const wrappedHandler = externalContextCreator.create(
    toolInstance,
    toolInstance[methodName],
    methodName,
    MCP_ARGS_METADATA,
    mcpParamsFactory,
    STATIC_CONTEXT,
    undefined,
    { guards: true, interceptors: true, filters: true },
    'mcp',  // contextType
  );
  ```
- `mcpParamsFactory` is a custom params factory that maps the MCP argument positions to the handler's expected parameters. It must handle the `@Ctx()` injection slot.
- The pipeline runner wraps each handler once at boot time (or lazily on first call), not per-request. Per-request data (identity, sessionId) flows through the `McpExecutionContextHost` args.
- Zod validation is done OUTSIDE the ExternalContextCreator pipeline — validate first, then call the wrapped handler with validated input
- Error normalization is implemented as a `McpExceptionFilter` (implements `ExceptionFilter`, decorated with `@Catch()`) registered as a built-in at module level — this allows consumers to override it with `@UseFilters()` or their own `APP_FILTER` registration
- The `McpExceptionFilter` handles:
  - `McpError` with `InvalidParams` or `MethodNotFound` code -> re-throw (protocol-level error)
  - `HttpException` -> extract status + message -> `{ isError: true }`
  - Other errors -> `{ isError: true }` with error message
- File location: `packages/nestjs-mcp/src/pipeline/mcp-pipeline-runner.ts`
- Reference NestJS source: `packages/core/helpers/external-context-creator.ts` for the `create()` method signature
