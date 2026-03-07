# AUTH-007: Component-level authorization

## Summary
Implement per-component authorization with two distinct mechanisms: (1) **list-time filtering** via `@RequiredScopes()` metadata decorator that hides components from `listTools`/`listResources`/`listPrompts` for unauthorized clients, and (2) **call-time enforcement** via standard NestJS `@UseGuards()` applied to handler methods. Includes helper functions `requireScopes()` (guard factory), `McpAuthorizationError`, `getAccessToken()`, and supporting types (`McpAuthContext`, `AccessToken`).

## Background / Context
**FastMCP parity**: FastMCP supports `@mcp.tool(auth=...)`, `@mcp.resource("uri", auth=...)`, `@mcp.prompt(auth=...)` for per-component authorization. It also provides helpers:
- `require_scopes(*scopes)` — validates token has ALL specified scopes
- `restrict_tag(tag, auth_check)` — applies auth check only to components with a specific tag (server-level)
- `run_auth_checks(checks, auth_context)` — executes a list of auth checks in sequence
- `AuthorizationError(message)` — custom error whose message IS propagated to client even when `maskErrorDetails: true`
- `get_access_token()` — retrieves current AccessToken from within any handler

In NestJS, component-level auth uses two standard patterns: (1) `@RequiredScopes()` (`SetMetadata`) for list-time filtering — `McpHandlerRegistry` reads this metadata during list operations, and (2) `@UseGuards(requireScopes('write'))` for call-time enforcement — `ExternalContextCreator` (CORE-010) ensures guards run for every MCP call.

## Acceptance Criteria

### List-time filtering (MCP-specific)
- [ ] `@RequiredScopes('admin')` decorator (via `SetMetadata`) stores required scopes in handler metadata
- [ ] During `listTools`, `McpHandlerRegistry` reads `RequiredScopes` metadata and evaluates against the current request's `AccessToken`
- [ ] If token is missing required scopes, the component is excluded from the list response (hidden, not error)
- [ ] If token has all required scopes, the component is included normally
- [ ] Components without `@RequiredScopes` are unaffected (always listed if other filters pass)

### Call-time enforcement (standard NestJS guards)
- [ ] `@UseGuards(requireScopes('admin'))` applied to tool/resource/prompt handler methods for call-time enforcement
- [ ] `requireScopes(...scopes: string[])` returns a `CanActivate` guard instance that reads `AccessToken` from `McpContext` and validates scopes
- [ ] If guard rejects, return "not found" error (same as if tool doesn't exist)
- [ ] If guard passes, proceed with normal execution
- [ ] NestJS guard pipeline AND global AuthGuard must both pass (AND logic)
- [ ] `ExternalContextCreator` (CORE-010) ensures guards run for every MCP call

### requireScopes helper (guard factory)
- [ ] `requireScopes(...scopes: string[])` exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Returns a `CanActivate` guard instance (usable with `@UseGuards(requireScopes('write'))`)
- [ ] Guard reads `AccessToken` from `McpContext` and validates ALL specified scopes are present
- [ ] When token is null (unauthenticated), guard rejects
- [ ] When token has all scopes, guard passes
- [ ] When token is missing any scope, guard rejects

### McpAuthorizationError
- [ ] `McpAuthorizationError` class exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Extends `Error` with a `message` property
- [ ] When thrown from a custom auth check or tool handler, the message IS propagated to the client even when `maskErrorDetails: true` (unlike generic errors)
- [ ] The pipeline runner (CORE-010) checks for `McpAuthorizationError` before applying error masking

### getAccessToken helper
- [ ] `getAccessToken()` exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Returns `AccessToken | null` for the current MCP request
- [ ] Callable from any service or tool handler during MCP request execution
- [ ] Uses `getMcpContext()` (CORE-024) internally to access the current request's identity and extract AccessToken
- [ ] Returns null when no auth is configured or request is unauthenticated

### Types
- [ ] `McpAuthContext` interface exported: `{ token: AccessToken | null }`
- [ ] `AccessToken` interface exported: `{ token: string, clientId?: string, scopes: string[], expiresAt?: Date, claims: Record<string, unknown> }`
- [ ] `RequiredScopes` metadata decorator exported from `@unique-ag/nestjs-mcp/auth`
- [ ] All types exported from `@unique-ag/nestjs-mcp/auth`
- [ ] To apply `@RequiredScopes` filtering at list time: `McpModule.forRoot({ pipeline: [RequiredScopesFilter, ...] })`. `RequiredScopesFilter` is a built-in pipeline component that reads `requiredScopes` from `RegistryEntry` metadata and calls `canActivate()` logic. Without this filter, `@RequiredScopes` only enforces at call time (not at list time).

## BDD Scenarios

```gherkin
Feature: Per-component authorization with scope-based access control

  Rule: Tools requiring scopes are hidden from unauthorized clients in list responses

    Scenario: Authorized client sees a scope-protected tool in the tool list
      Given a tool "delete-user" requires the "admin" scope
      And a client is authenticated with scopes "admin" and "user:read"
      When the client requests the list of available tools
      Then "delete-user" appears in the tool list

    Scenario: Unauthorized client does not see a scope-protected tool
      Given a tool "delete-user" requires the "admin" scope
      And a client is authenticated with only the "user:read" scope
      When the client requests the list of available tools
      Then "delete-user" does not appear in the tool list

    Scenario: Unauthenticated client does not see scope-protected tools
      Given a tool "delete-user" requires the "admin" scope
      And a client connects without authentication
      When the client requests the list of available tools
      Then "delete-user" does not appear in the tool list

    Scenario: Tools without scope requirements are always listed
      Given a tool "list-users" has no scope requirements
      And a client is authenticated with any scopes
      When the client requests the list of available tools
      Then "list-users" appears in the tool list

  Rule: Calling a scope-protected tool is enforced at execution time

    Scenario: Authorized client successfully calls a scope-protected tool
      Given a tool "delete-user" requires the "admin" scope
      And a client is authenticated with the "admin" scope
      When the client calls "delete-user"
      Then the tool executes successfully

    Scenario: Unauthorized client calling a scope-protected tool gets "not found"
      Given a tool "delete-user" requires the "admin" scope
      And a client is authenticated with only the "user:read" scope
      When the client calls "delete-user" by name
      Then the client receives a "tool not found" error
      And the response does not reveal that the tool exists but is unauthorized

    Scenario: Both global authentication and component-level scopes must pass
      Given a tool "delete-user" requires the "admin" scope
      And a client has a valid authentication token but only the "user:read" scope
      When the client calls "delete-user"
      Then authentication succeeds at the global level
      But the scope check rejects the call
      And the client receives a "tool not found" error

  Rule: Tool handlers can access the current client's access token

    Scenario: Tool handler retrieves the current access token
      Given a client is authenticated with scopes "mail.read" and "mail.send"
      When a tool handler retrieves the current access token
      Then the token includes scopes "mail.read" and "mail.send"
      And the token includes the client ID, expiration, and claims

    Scenario: Access token retrieval returns nothing for unauthenticated requests
      Given no authentication is configured on the MCP server
      When a tool handler retrieves the current access token
      Then no token is returned

  Rule: Authorization errors bypass error masking

    Scenario: Authorization error message is visible to the client even when error masking is enabled
      Given error detail masking is enabled on the MCP server
      And a tool throws an authorization error with message "Subscription expired"
      When the client receives the error response
      Then the error message reads "Subscription expired"
      And the message is not masked or replaced with a generic error
```

## Dependencies
- **Depends on:** CORE-006 — `McpIdentity` as the token source for building `McpAuthContext`
- **Depends on:** CORE-010 — `ExternalContextCreator` ensures guards run for every MCP call
- **Depends on:** CORE-013 — list-time handler must read `RequiredScopes` metadata for filtering
- **Depends on:** AUTH-001 — auth module infrastructure (`McpAuthModule`, `McpAuthProvider`)
- **Blocks:** none

## Technical Notes

- Call-time authorization uses standard `@UseGuards(requireScopes('write'))` or a custom `CanActivate` guard applied directly to the method — `ExternalContextCreator` (CORE-010) ensures guards run for every MCP call
- List-time filtering (hiding tools from `listTools` for unauthorized clients) is MCP-specific — implemented via `@RequiredScopes('read')` metadata decorator (`SetMetadata`) that `McpHandlerRegistry` reads during list operations
- `McpAuthorizationError` is handled by a built-in `@Catch(McpAuthorizationError)` exception filter that always propagates the error message to the client, bypassing `maskErrorDetails` — consumers can override with their own `@UseFilters()`

### Type definitions
```typescript
// Exported from @unique-ag/nestjs-mcp/auth

export interface AccessToken {
  token: string;
  clientId?: string;
  scopes: string[];
  expiresAt?: Date;
  claims: Record<string, unknown>;
}

export interface McpAuthContext {
  token: AccessToken | null;
}

export class McpAuthorizationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'McpAuthorizationError';
  }
}
```

### requireScopes implementation (guard factory)
```typescript
import { CanActivate, ExecutionContext } from '@nestjs/common';

export function requireScopes(...scopes: string[]): CanActivate {
  return {
    canActivate(context: ExecutionContext): boolean {
      const mcpCtx = getMcpContext(); // from CORE-024
      const token = getAccessToken();
      if (!token) return false;
      return scopes.every(scope => token.scopes.includes(scope));
    },
  };
}
```

### RequiredScopes metadata decorator (list-time filtering)
```typescript
import { SetMetadata } from '@nestjs/common';

export const REQUIRED_SCOPES_KEY = 'mcp:required-scopes';
export const RequiredScopes = (...scopes: string[]) => SetMetadata(REQUIRED_SCOPES_KEY, scopes);
```

### getAccessToken implementation
```typescript
export function getAccessToken(): AccessToken | null {
  const mcpCtx = getMcpContext(); // from CORE-024
  if (!mcpCtx?.identity) return null;
  // Map McpIdentity to AccessToken
  return {
    token: mcpCtx.identity.raw as string,
    clientId: mcpCtx.identity.clientId,
    scopes: mcpCtx.identity.scopes ?? [],
    expiresAt: mcpCtx.identity.expiresAt,
    claims: mcpCtx.identity.claims ?? {},
  };
}
```

### List-time evaluation
In handlers (CORE-013), the list operation reads `RequiredScopes` metadata for each component:

```typescript
// In McpToolsHandler.listTools()
for (const entry of registry.getAllTools()) {
  const requiredScopes = Reflect.getMetadata(REQUIRED_SCOPES_KEY, entry.handler);
  if (requiredScopes?.length) {
    const token = getAccessToken();
    if (!token || !requiredScopes.every(s => token.scopes.includes(s))) {
      continue; // skip — hidden from list
    }
  }
  // ... include in response
}
```

### Usage example
```typescript
@Tool({ description: 'Delete user' })
@RequiredScopes('admin')              // list-time: hide from listTools if client lacks 'admin'
@UseGuards(requireScopes('admin'))    // call-time: reject direct calls without 'admin' scope
async deleteUser(@McpParam() userId: string): Promise<string> {
  // ...
}
```

### Interaction with TagScopeGuard (CORE-015)
Component-level `auth` and `TagScopeGuard` are complementary:
- `auth` on decorator: per-component, explicit, stored in metadata
- `TagScopeGuard`: tag-based, implicit, configured at module level
- Both are evaluated — if either rejects, the component is hidden/denied

### FastMCP parity
| FastMCP | NestJS equivalent |
|---|---|
| `@mcp.tool(auth=require_scopes('admin'))` | `@RequiredScopes('admin') @UseGuards(requireScopes('admin'))` |
| `@mcp.resource("uri", auth=require_scopes('read'))` | `@RequiredScopes('read') @UseGuards(requireScopes('read'))` |
| `require_scopes(*scopes)` | `requireScopes(...scopes: string[])` (returns `CanActivate` guard) |
| `AuthorizationError(message)` | `McpAuthorizationError(message)` |
| `get_access_token()` | `getAccessToken()` |
| `restrict_tag(tag, auth_check)` | Covered by `TagScopeGuard` in CORE-015 |
| `run_auth_checks(checks, auth_context)` | Not needed — NestJS guard chain handles sequential checks |

### Handler registry integration
Handler registry integration: `McpHandlerRegistry.getEntry(name)` returns the `RegistryEntry` which includes any `requiredScopes` metadata from `@RequiredScopes()`. The pipeline runner (CORE-010) reads this metadata when constructing the execution context for list-time guard checks.

### File locations
- `packages/nestjs-mcp/src/auth/helpers/require-scopes.ts`
- `packages/nestjs-mcp/src/auth/helpers/get-access-token.ts`
- `packages/nestjs-mcp/src/auth/types/auth-check.types.ts`
- `packages/nestjs-mcp/src/auth/errors/authorization.error.ts`
