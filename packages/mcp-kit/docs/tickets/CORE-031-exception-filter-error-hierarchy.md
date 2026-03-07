# CORE-031: McpExceptionFilter & Error Hierarchy

## Summary
Implement the foundational error class hierarchy (`McpBaseError`, `DefectError`, `invariant()`) and the two catch boundaries (`handleMcpToolError()` at MCP handler level, `McpHttpExceptionFilter` at HTTP level) that formalize the defect vs failure model used throughout the framework.

## Background / Context
Error handling across CORE, AUTH, and CONN tickets currently references named error classes (`UpstreamConnectionRequiredError`, `McpAuthorizationError`, etc.) without a shared base. This ticket defines that base and the two boundaries that catch errors at each layer of the stack.

The model follows the [Effect two-error-types pattern](https://effect.website/docs/error-management/two-error-types/) adapted for NestJS:
- **Failures** (`McpBaseError` subclasses) — expected domain errors, return graceful `{ isError: true }` responses to clients
- **Defects** (`DefectError` via `invariant()`) — programming errors / invariant violations, return generic "internal error", logged at ERROR with full stack

This ticket must land first as it is a dependency for CORE-010, CORE-013, AUTH-001, AUTH-007, CONN-004, and SDK-001.

## Acceptance Criteria

### `invariant()` and `DefectError`

- [ ] `src/errors/defect.ts` exports:
  - `DefectError extends Error` — `readonly _tag = 'Defect' as const`, `name = 'DefectError'`
  - `invariant(condition: unknown, message: string): asserts condition` — throws plain `Error` (not `DefectError`) when `condition` is falsy
- [ ] `invariant()` uses the TypeScript `asserts condition` type predicate — TypeScript narrows the type after the call
- [ ] `invariant()` throws plain `Error` (not `DefectError`) so it is framework-agnostic and extractable to `@unique-ag/utils` with zero changes. The catch boundaries treat unknown `Error` as a defect automatically (case 5 in `handleMcpToolError`).
- [ ] `DefectError` is distinguishable from `McpBaseError` at runtime via `._tag` — used for **explicit** defect annotation at the throw site
- [ ] `invariant()` is exported from `@unique-ag/mcp-kit`
- [ ] Node's `assert` from `node:assert` is NOT used — `DefectError` must be distinguishable from `AssertionError`

### `McpBaseError` and `McpErrorMetadata`

- [ ] `src/errors/base.ts` exports:
  - `McpErrorMetadata` interface: `{ mcpErrorCode?: number; retryable?: boolean; context?: Record<string, unknown> }`
  - `McpBaseError extends Error` — `abstract`, `readonly _tag = 'McpFailure' as const`, `abstract readonly errorCode: string`, constructor `(message, metadata?, options?)`
- [ ] `McpBaseError` is never thrown directly — only concrete subclasses
- [ ] `McpBaseError` is exported from `@unique-ag/mcp-kit`

### Concrete failure classes

- [ ] `src/errors/failures.ts` exports all concrete subclasses:

| Class | `errorCode` | `mcpErrorCode` | `retryable` | Notes |
|-------|------------|----------------|-------------|-------|
| `McpAuthenticationError` | `MCP_AUTHENTICATION_FAILED` | `ErrorCode.InvalidRequest` | `false` | Token missing or malformed |
| `McpAuthorizationError` | `MCP_AUTHORIZATION_FAILED` | `ErrorCode.InvalidRequest` | `false` | Valid token, wrong scopes |
| `McpValidationError` | `MCP_VALIDATION_FAILED` | `ErrorCode.InvalidParams` | `false` | Input schema mismatch |
| `McpToolError` | `MCP_TOOL_ERROR` | — | `false` | Catch-all for tool domain errors |
| `McpProtocolError` | `MCP_PROTOCOL_ERROR` | caller-supplied | `false` | Maps to SDK `McpError` codes |
| `UpstreamConnectionRequiredError` | `MCP_UPSTREAM_CONNECTION_REQUIRED` | — | `true` | Extra fields: `upstreamName: string`, `reconnectUrl: string` |
| `UpstreamConnectionLostError` | `MCP_UPSTREAM_CONNECTION_LOST` | — | `true` | Extra field: `upstreamName: string` |

- [ ] All concrete failure classes are exported from `@unique-ag/mcp-kit`
- [ ] `McpElicitationError`, `McpElicitationDeclinedError`, `McpElicitationCancelledError`, `McpElicitationTimeoutError` (defined in SDK-001) extend `McpBaseError` — their base class is defined here, subclasses in SDK-001

### `handleMcpToolError()` — MCP handler boundary

- [ ] `src/errors/mcp-exception-handler.ts` exports `handleMcpToolError(error: unknown): McpToolErrorResponse`
- [ ] Behaviour by error type:
  1. `McpError` (SDK) → **rethrow** (transport layer handles protocol errors)
  2. `UpstreamConnectionRequiredError` → **rethrow** (reconnection pipeline must intercept before filter)
  3. `McpBaseError` → log WARN with `errorCode` + `context`; return `{ isError: true, content: [{ type: 'text', text: error.message }] }`
  4. `DefectError` → log ERROR with full stack; return `{ isError: true, content: [{ type: 'text', text: 'Internal server error. This is a bug.' }] }`
  5. Unknown `Error` / other → treat as defect: log ERROR with full stack; return `{ isError: true, content: [{ type: 'text', text: 'An unexpected error occurred.' }] }`
- [ ] Client-facing messages for defects and unknowns never include the original error message or stack
- [ ] `McpToolsHandler`, `McpResourcesHandler`, `McpPromptsHandler` all replace their ad-hoc catch blocks with `return handleMcpToolError(error)`

### `McpHttpExceptionFilter` — HTTP transport boundary

- [ ] `src/filters/mcp-http-exception.filter.ts` exports `McpHttpExceptionFilter implements ExceptionFilter`
- [ ] `@Catch()` with no arguments — catches all unhandled exceptions at the HTTP/guard level
- [ ] Behaviour by error type:
  1. `HttpException` (NestJS) → respond with `error.getStatus()` + `error.getResponse()` (standard NestJS behaviour)
  2. `UpstreamConnectionRequiredError` → HTTP 401 with JSON-RPC error body `{ code: -32001, message, data: { reconnectUrl } }`
  3. `McpBaseError` → HTTP 400 with JSON-RPC error body `{ code: metadata.mcpErrorCode ?? -32000, message }`; log WARN
  4. `DefectError` → HTTP 500 with `{ code: -32603, message: 'Internal server error' }`; log ERROR with full stack
  5. Unknown → treat as defect: HTTP 500; log ERROR with full stack; never leak original message
- [ ] Registered globally in `McpModule` via `{ provide: APP_FILTER, useClass: McpHttpExceptionFilter }`
- [ ] `McpHttpExceptionFilter` is exported from `@unique-ag/mcp-kit` for consumers who want to register it manually

### Barrel exports

- [ ] `src/errors/index.ts` re-exports all error classes, `invariant`, `handleMcpToolError`
- [ ] All of the above are available from the `@unique-ag/mcp-kit` top-level export

### Branded types (owned by this module)

- [ ] `src/errors/` uses `UserId`, `ClientId` from `src/types/brands.ts` (cross-cutting, INFRA-001) where needed in error metadata

## BDD Scenarios

```gherkin
Feature: McpExceptionFilter & Error Hierarchy

  Rule: Failures return graceful tool error responses

    Scenario: McpBaseError subclass thrown from a tool handler
      Given a tool handler that throws McpAuthorizationError("Insufficient scopes")
      When the tool is called
      Then handleMcpToolError returns { isError: true, content: [{ type: 'text', text: 'Insufficient scopes' }] }
      And a WARN log is emitted with the errorCode

    Scenario: UpstreamConnectionRequiredError is rethrown for the reconnection pipeline
      Given a tool handler that throws UpstreamConnectionRequiredError("microsoft-graph", reconnectUrl)
      When handleMcpToolError processes it
      Then UpstreamConnectionRequiredError is rethrown
      And no { isError: true } response is produced

  Rule: Defects return generic error responses and log the full stack

    Scenario: invariant() failure produces a DefectError
      Given a tool handler that calls invariant(false, "token must exist after auth guard")
      When the tool is called
      Then handleMcpToolError returns { isError: true, content: [{ type: 'text', text: 'Internal server error. This is a bug.' }] }
      And an ERROR log is emitted with the full stack trace
      And the invariant message is NOT included in the client response

    Scenario: Unknown error is treated as a defect
      Given a tool handler that throws new TypeError("Cannot read property 'x' of undefined")
      When handleMcpToolError processes it
      Then the client receives { isError: true, content: [{ type: 'text', text: 'An unexpected error occurred.' }] }
      And the TypeError message does NOT appear in the client response

  Rule: invariant() narrows TypeScript types

    Scenario: TypeScript type narrowing after invariant()
      Given a value typed as string | undefined
      When invariant(value !== undefined, "value must be defined") is called
      Then TypeScript considers value to be string after that line (compile-time narrowing)

  Rule: McpHttpExceptionFilter handles guard-level failures

    Scenario: McpAuthenticationError thrown from McpAuthGuard
      Given a request with a missing Bearer token
      And McpAuthGuard throws McpAuthenticationError
      When the request is processed
      Then McpHttpExceptionFilter returns HTTP 400 with JSON-RPC error body
      And a WARN log is emitted

    Scenario: NestJS HttpException passes through unchanged
      Given a guard that throws ForbiddenException (NestJS HttpException)
      When McpHttpExceptionFilter catches it
      Then the response uses HTTP 403 with the standard NestJS error body
      And the framework does not interfere with the default behaviour

    Scenario: DefectError at HTTP level returns 500 and logs full stack
      Given middleware that throws a DefectError("impossible state")
      When McpHttpExceptionFilter catches it
      Then the client receives HTTP 500 with { code: -32603, message: 'Internal server error' }
      And the defect message is NOT in the HTTP response
      And an ERROR log with the full stack is emitted
```

## FastMCP Parity
FastMCP (Python) has no formal defect/failure distinction. Our model is inspired by Effect's two-error-types and Rust's `panic` vs `Result` dichotomy, adapted for NestJS idioms.

## Dependencies
- **Depends on:** INFRA-001 (package scaffold)
- **Blocks:** CORE-010 (pipeline runner references `UpstreamConnectionRequiredError`), CORE-013 (McpToolsHandler uses `handleMcpToolError()`), CORE-027, CORE-028 (same), AUTH-001 (McpAuthenticationError, McpAuthorizationError), AUTH-007 (McpAuthorizationError), CONN-003 (UpstreamConnectionLostError), CONN-004 (UpstreamConnectionRequiredError), SDK-001 (McpElicitationError subclasses)

## Technical Notes
- `invariant()` should be favoured over `if (!x) throw new Error(...)` for all "this should never happen" checks. The `asserts condition` return type is what makes it useful — it eliminates subsequent undefined-checks in TypeScript without an explicit cast.
- `invariant()` throws plain `Error` (not `DefectError`) intentionally. This keeps it framework-agnostic: if it is later extracted to `@unique-ag/utils`, zero code changes are required. The catch boundaries already treat unknown `Error` as a defect (case 5 in `handleMcpToolError`), so the client-visible behaviour is identical. Use `throw new DefectError(message)` only when you want an explicit, tagged defect at the throw site.
- `src/errors/` is a **self-contained subpath module** — no imports from other mcp-kit subpaths (`src/session/`, `src/auth/`, etc.) and no `@nestjs/*` imports. This enforces the extractability contract (see conventions.md § Subpath Module Design).
- The `context` field in `McpErrorMetadata` is for internal logging only. It is never serialized into the client response. Use it to attach request IDs, user IDs, or other debugging context without risking information leakage.
- `McpHttpExceptionFilter` is registered with `@Catch()` (no argument), making it a global catch-all. It explicitly re-handles `HttpException` using the standard NestJS pattern so that guards producing `ForbiddenException`, `UnauthorizedException`, etc. still work as expected.
- The reconnection pipeline (CONN-005) must be positioned to intercept `UpstreamConnectionRequiredError` before the HTTP filter catches it. If the pipeline is implemented as a NestJS interceptor, it runs inside the guard/filter stack and will see the rethrown error before `McpHttpExceptionFilter` does.
