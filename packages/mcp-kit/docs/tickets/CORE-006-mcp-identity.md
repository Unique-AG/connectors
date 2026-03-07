# CORE-006: McpIdentity interface + McpIdentityResolver

## Summary
Define the `McpIdentity` interface and implement the `McpIdentityResolver` (REQUEST-scoped) that builds an `McpIdentity` from `request.user` (a `TokenValidationResult` with denormalized `userData`). This eliminates the need for tools to access raw request objects or call `IOAuthStore` at request time.

## Background / Context
The `McpIdentity` interface provides a clean, typed representation of the authenticated user. `McpIdentityResolver` (REQUEST-scoped) builds an `McpIdentity` from `request.user` once per request. Profile data (email, displayName) is denormalized into the token at issuance time in `AccessTokenMetadata.userData`, so the resolver builds the full identity purely from `request.user` without any DB lookup.

The `McpIdentity` interface lives in the **core** entrypoint (not auth), so tools can depend on it without importing auth. The resolver reads from `request.user` which is set by the auth guard (in the auth sub-entrypoint).

## Acceptance Criteria
- [ ] `McpIdentity` interface exported from `@unique-ag/nestjs-mcp` with fields: `userId`, `profileId`, `clientId`, `email` (string | undefined), `displayName` (string | undefined), `scopes` (string[]), `resource` (string), `raw` (unknown)
- [ ] `McpIdentityResolver` is `@Injectable({ scope: Scope.REQUEST })`
- [ ] Resolver reads `request.user` (injected via `@Inject(REQUEST)`)
- [ ] Maps `TokenValidationResult` fields to `McpIdentity`: `userId`, `clientId`, `scope` -> `scopes` (split by space), `resource`, `userProfileId` -> `profileId`, `userData.email` -> `email`, `userData.displayName` -> `displayName`
- [ ] Returns `null` when `request.user` is undefined (unauthenticated server)
- [ ] `getMcpIdentity(context: ExecutionContext): McpIdentity | null` helper function exported
- [ ] `getMcpIdentity` returns `null` for non-MCP contexts (`context.getType() !== 'mcp'`)
- [ ] No dependency on `IOAuthStore` or any auth-specific service

## BDD Scenarios

```gherkin
Feature: McpIdentity resolution from authenticated requests

  Rule: Identity is built from the authenticated user on each request

    Scenario: Authenticated request produces a complete identity
      Given a user authenticated with user ID "u1", client ID "c1", scopes "mail.read mail.send", and profile ID "p1"
      And the user's profile has email "user@example.com" and display name "Test User"
      When a tool is invoked in this request
      Then the identity has user ID "u1"
      And the identity has profile ID "p1"
      And the identity has client ID "c1"
      And the identity has email "user@example.com"
      And the identity has display name "Test User"
      And the identity has scopes "mail.read" and "mail.send"

    Scenario: Single scope is parsed correctly
      Given a user authenticated with scopes "mail.read"
      When a tool is invoked in this request
      Then the identity has exactly one scope "mail.read"

    Scenario: Missing profile fields result in undefined
      Given a user authenticated without email or display name in their profile
      When a tool is invoked in this request
      Then the identity has email undefined
      And the identity has display name undefined
      And all other identity fields are populated

    Scenario: Original token data is accessible via the raw field
      Given a user authenticated with extra fields beyond the standard set
      When a tool accesses the identity's raw field
      Then it contains the original authentication data

  Rule: Unauthenticated requests produce a null identity

    Scenario: Unauthenticated request has no identity
      Given a request with no authenticated user
      When the identity resolver runs
      Then the result is null

  Rule: getMcpIdentity helper works across execution context types

    Scenario: getMcpIdentity returns the identity in an MCP context
      Given a guard running in an MCP execution context with an authenticated user
      When the guard calls getMcpIdentity
      Then it receives the resolved McpIdentity

    Scenario: getMcpIdentity returns null in an HTTP context
      Given a guard running in a standard HTTP execution context
      When the guard calls getMcpIdentity
      Then it receives null
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Depends on: CORE-005 — registry is available (resolver is wired during module bootstrap)
- Depends on: CORE-009 — `switchToMcp()` needed for `getMcpIdentity` helper
- Blocks: CORE-007 — McpContext uses McpIdentity
- Blocks: CORE-011 — built-in guards use getMcpIdentity
- Blocks: AUTH-002 — token userData denormalization maps to McpIdentity

## Interface Contract
Consumed by CORE-007 (McpContext), CORE-009 (McpOperationContext), CORE-011 (guards), AUTH-002:
```typescript
export interface McpIdentity {
  userId: string;
  profileId: string;
  clientId: string;
  email: string | undefined;
  displayName: string | undefined;
  scopes: string[];
  resource: string;
  raw: unknown;                          // original request.user; cast to TokenValidationResult if needed
}

export function getMcpIdentity(context: ExecutionContext): McpIdentity | null;
```

## Technical Notes
- `McpIdentity` interface — keep `raw` typed as `unknown` in the core entrypoint. Consumers who import auth can cast to `TokenValidationResult` if needed.
- The resolver does NOT need to be used directly by tools. The `McpExecutorService` (CORE-013) calls the resolver once per request and passes the identity into `McpContext`.
- `getMcpIdentity` implementation:
  ```typescript
  export function getMcpIdentity(context: ExecutionContext): McpIdentity | null {
    if (context.getType() !== 'mcp') return null;
    return context.switchToMcp().getMcpContext().identity;
  }
  ```
- File locations:
  - `packages/nestjs-mcp/src/interfaces/mcp-identity.interface.ts` (interface)
  - `packages/nestjs-mcp/src/services/mcp-identity-resolver.service.ts` (resolver)
  - `packages/nestjs-mcp/src/helpers/get-mcp-identity.ts` (helper function)
- The `scope` field in `TokenValidationResult` is a space-separated string per OAuth spec; split on space to produce `scopes: string[]`
