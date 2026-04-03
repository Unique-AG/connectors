# @unique-ag/mcp-kit — Development Conventions

## Branded Types

Use `z.brand()` to create nominal types. Choose the most specific Zod validator for the underlying format, then add `.brand()` last:

```typescript
// Correct — validator matches the underlying format
export const SessionId    = z.string().uuid().brand('SessionId');   // UUIDs
export const JwksUri      = z.string().url().brand('JwksUri');      // URLs
export const HmacSecret   = z.string().min(32).brand('HmacSecret'); // min-length key
export const ProviderId   = z.string().min(1).brand('ProviderId');  // opaque slug

// Inferred type alongside the schema
export type SessionId = z.infer<typeof SessionId>;
```

Never use the manual `Brand<T, B>` utility type pattern — Zod brands give you both compile-time enforcement and a runtime parser for free.

**Where to define them:**
- Cross-cutting types used by 3+ modules → `src/types/brands.ts` (INFRA-001)
- Module-specific types → `<module>/types.ts`, re-exported from `src/types/index.ts`

**How to use them:**
- At parse boundaries (external data): `UserId.parse(payload.sub)` — throws on invalid input
- When you already hold a trusted value: `value as UserId` — compile-time only, no runtime cost

## null vs undefined

**Rule: `undefined`-only for all optional fields and "not found" returns.**

| Scenario | Convention |
|----------|------------|
| Optional interface field | `field?: T` — never `field: T \| null` |
| "Not found" / "not registered" return | `T \| undefined` — never `T \| null` |
| External null (DB columns, JSON) | Coerce to `undefined` in the store/mapper; never propagate inward |
| Zod schemas for external data | `.nullable()` only at the DB/HTTP boundary; `.optional()` inside the domain |

**Two named exceptions where `null` is correct:**

1. `identity: McpIdentity | null` (CORE-006/007, SESS-005, TRANS-001/003)
   `null` = authentication is explicitly disabled (zero-auth). This is an architectural contract — `undefined` would mean "not yet resolved", a different state.

2. `clientInfo: { name: string; version: string } | null` (CORE-007, SESS-001/004)
   `null` = client sent no clientInfo during the MCP handshake. Also required for Redis/Drizzle serialization boundaries.

**Enforce with `tsconfig.json`:**
```json
{ "compilerOptions": { "exactOptionalPropertyTypes": true } }
```

## Zod at Boundaries

Validate all external data before it enters the domain — never cast with `as`:

- JWT payload claims → `JwtClaimsSchema.parse(payload)` before field access
- OIDC discovery documents → `OidcDiscoveryDocumentSchema.parse(await response.json())`
- OAuth token responses → `OAuthTokenResponseSchema.parse(await response.json())`
- DB JSON columns → `TokenUserDataSchema.nullable().parse(row.userData)`
- Redis/cache reads → `SessionRecordSchema.parse(JSON.parse(raw))`
- Module options → validate in `forRoot()` / constructor, throw at startup not at first request

## Discriminated Unions over Optional Fields

When an interface has optional fields that represent mutually exclusive modes, use a discriminated union instead:

```typescript
// Wrong — invalid combinations are representable
interface McpUpstreamConfig {
  url?: string;
  command?: string;
}

// Correct — impossible states are unrepresentable
type McpUpstreamConfig =
  | { kind: 'http';  url: string }
  | { kind: 'stdio'; command: string };
```

Key discriminated unions in this codebase:
- `TokenValidationResult` — `source: 'oauth' | 'jwt'`
- `McpUpstreamConfig` — `kind: 'http' | 'stdio' | 'npx' | 'uvx'`
- `McpRequestContext` — `authenticated: true | false`
- `ElicitationResult` — `action: 'completed' | 'declined' | 'error' | 'timeout'`

## Defects vs Failures

Errors in this framework fall into two categories with different handling rules. This mirrors the [Effect two-error-types model](https://effect.website/docs/error-management/two-error-types/) without requiring the Effect library.

### Failures — expected, typed, handled

A **failure** is an anticipated domain error. It is part of the normal operating envelope. Examples: token expired, upstream connection missing, insufficient scopes, invalid input.

- Extend `McpBaseError` (defined in CORE-031)
- Always carry a human-readable `message` safe to return to the MCP client
- Caught by `handleMcpToolError()` at the MCP handler level → returned as `{ isError: true, content: [...] }`
- Caught by `McpHttpExceptionFilter` at the HTTP level → returned as a JSON-RPC error response
- Logged at `WARN` level

```typescript
// Good — expected, typed, returns a graceful MCP error response
throw new UpstreamConnectionRequiredError('microsoft-graph', reconnectUrl);
throw new McpAuthorizationError('Insufficient scopes: Files.Read required');
throw new McpValidationError('folderId must be a non-empty string');
```

### Defects — unexpected, invariant violations, bugs

A **defect** is a programming error — something that should never happen in correct code. Examples: a required dependency is `undefined` after DI, a code path that should be unreachable was reached, a store returned `undefined` after a guard guaranteed it wouldn't.

- Use `invariant()` (defined in CORE-031) — NOT `throw new Error(...)`, NOT Node's `assert`
- `invariant()` throws `DefectError`, which is distinguishable from `McpBaseError` at runtime
- Caught by `handleMcpToolError()` or `McpHttpExceptionFilter` → returns a generic "internal error" message, **never leaks the invariant message to the client**
- Logged at `ERROR` level with full stack trace

```typescript
import { invariant } from '@unique-ag/mcp-kit';

// Good — asserts a programming invariant; the message is for developers, not clients
const token = await this.tokenStore.get(sessionId);
invariant(token !== undefined, `Token store returned undefined for session ${sessionId} after McpAuthGuard ran`);
// TypeScript now narrows: token is defined

// Wrong — raw Error leaks message to client and is indistinguishable from a failure
if (!token) throw new Error('token is undefined'); // ❌
```

### The `invariant()` signature

```typescript
/**
 * Assert a runtime invariant. Throws plain Error if false.
 * TypeScript narrows the type of `condition` after this call.
 *
 * Throws plain Error (not DefectError) so this function is framework-agnostic
 * and can be extracted to @unique-ag/utils with zero changes.
 * The catch boundaries treat unknown Error as a defect automatically.
 */
export function invariant(condition: unknown, message: string): asserts condition;
```

`DefectError` is for cases where you want to **explicitly annotate** a defect at the throw site. `invariant()` relies on the catch boundaries treating unknown `Error` as a defect (case 5 in `handleMcpToolError`). Both reach the same outcome for the client.

### Catch boundaries

There are two catch boundaries — each error type must reach the right one:

| Boundary | Catches | Returns |
|----------|---------|---------|
| `handleMcpToolError()` (MCP handler) | Failures + Defects thrown during tool/resource/prompt execution | `{ isError: true, content: [...] }` |
| `McpHttpExceptionFilter` (HTTP level) | Failures + Defects thrown from guards or middleware (before handler runs) | JSON-RPC error response |

`UpstreamConnectionRequiredError` is the one failure that is **rethrown** at the MCP handler boundary — the `McpReconnectionPipeline` must intercept it before the filter does.

### Existing error classes

All existing named errors in the framework extend `McpBaseError` (failures):

| Class | Thrown by | Caught by |
|-------|-----------|-----------|
| `McpAuthenticationError` | `McpAuthGuard` | `McpHttpExceptionFilter` |
| `McpAuthorizationError` | `McpAuthGuard`, tool handlers | Both boundaries |
| `UpstreamConnectionRequiredError` | `McpConnectionGuard` | Reconnection pipeline (rethrown by handler boundary) |
| `UpstreamConnectionLostError` | Tool handlers mid-execution | `handleMcpToolError()` |
| `McpValidationError` | Zod parse failures in handlers | `handleMcpToolError()` |
| `McpToolError` | Tool handlers (catch-all domain error) | `handleMcpToolError()` |
| `McpElicitationError` and subclasses | `ctx.elicit()` | `handleMcpToolError()` |

## Subpath Module Design (extractability)

`@unique-ag/mcp-kit` is organized into subpath modules (`/errors`, `/types`, `/brands`, `/session`, `/auth`, `/connection`). Each subpath is designed so it can be extracted into a standalone package with zero code changes — just a new `package.json` and a re-export shim in mcp-kit.

**Rules for each subpath module:**

1. **No cross-subpath imports.** A file in `src/errors/` must not import from `src/session/` or `src/auth/`. Allowed deps: external packages (`zod`, `@modelcontextprotocol/sdk`) only. Enforced by INFRA-003 lint rule.
2. **No NestJS in leaf modules.** `src/errors/`, `src/types/`, `src/brands/`, `src/session/` must not import `@nestjs/*`. NestJS is only allowed in handler/module/guard/filter files that are NOT part of a subpath export.
3. **Each subpath has its own barrel.** `src/errors/index.ts`, `src/types/index.ts`, etc. The root `src/index.ts` re-exports from all subpath barrels. This means extraction = copy the subpath directory + publish.

```
src/
  errors/       ← extractable: pure TS, zero NestJS
    index.ts
    base.ts
    defect.ts
    failures.ts
    mcp-exception-handler.ts
  types/         ← extractable: pure TS, zero NestJS
    index.ts
    brands.ts
  session/       ← extractable: pure TS, zero NestJS
    index.ts
  auth/          ← extractable: pure TS, zero NestJS
    index.ts
  connection/    ← extractable: pure TS, zero NestJS
    index.ts
  filters/       ← NOT extractable: NestJS ExceptionFilter
  guards/        ← NOT extractable: NestJS CanActivate
  decorators/    ← NOT extractable: NestJS SetMetadata / UseGuards
  module/        ← NOT extractable: NestJS @Module
  index.ts       ← re-exports all subpaths
```

**When to extract:** When a concrete consumer outside `@unique-ag/mcp-kit` needs the types (e.g., `@unique-ag/utils` wants `invariant()`, or a client-side error handler needs `McpBaseError`). Until then, subpath imports give identical ergonomics at zero overhead.
