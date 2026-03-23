# EXTRACTION-PROPOSAL-V2.md

Updated extraction proposal based on actual monorepo analysis. Supersedes the original EXTRACTION-CANDIDATES.md placement recommendations.

---

## 1. Immediate Wins: Add to `@unique-ag/utils` Now

These have **proven duplication** in the monorepo today.

### 1a. `normalizeError(error: unknown): Error`

**Evidence:** Copy-pasted in 5 locations with slight variations:
- `services/teams-mcp/src/utils/normalize-error.ts` (full version, 18 lines)
- `services/sharepoint-connector/src/utils/normalize-error.ts` (full + `sanitizeError` helper)
- `services/outlook-mcp/src/utils/normalize-error.ts` (full version)
- `services/factset-mcp/src/utils/normalize-error.ts` (simplified 3-line version)
- `packages/mcp-oauth/src/utils/normalize-error.ts` (full version)

**Action:** Add `normalizeError()` to `@unique-ag/utils` main export. Use the full (teams-mcp) version as the canonical implementation. Zero new dependencies needed.

**Consumers to update:** teams-mcp, sharepoint-connector, outlook-mcp, factset-mcp, mcp-oauth (5 packages). Each deletes their local copy and imports from `@unique-ag/utils`.

> Note: sharepoint-connector also has `sanitizeError()` that wraps `normalizeError` + `serialize-error-cjs`. That stays local since it has a third-party dependency and is only used in one service.

---

## 2. New Primitives for `@unique-ag/utils`

These are being introduced in mcp-kit but have clear value beyond MCP contexts.

### 2a. `invariant(condition, message): asserts condition`

**Why utils, not mcp-kit:**
- The monorepo has **20+ instances** of `if (!x) throw new Error(...)` across services (outlook-mcp, outlook-semantic-mcp, factset-mcp, teams-mcp, mcp-server-module, aes-gcm-encryption, etc.)
- `invariant()` is a well-known pattern (used in React, tiny-invariant, ts-invariant) — it's not MCP-specific
- It's a zero-dependency function: `function invariant(condition: unknown, message: string): asserts condition`
- Every package in the monorepo could benefit from it

**What to add:**
```typescript
// packages/utils/src/invariant.ts
export function invariant(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}
```

**What stays in mcp-kit:** `DefectError` class and an MCP-specific `invariant` that throws `DefectError` instead of plain `Error`. The mcp-kit version builds on the concept but throws a richer error type. See section 3.

### 2b. `Brand<T>` utility type (not Zod-dependent)

**Why NOT utils:**
After analysis, branded types should **stay in mcp-kit**. Here's why:
- Zero branded types exist anywhere in the monorepo today
- The branded types in mcp-kit (`BearerToken`, `HmacSecret`, `Scope`, `UserId`, `ClientId`, `ProviderId`) are all MCP/auth-specific
- `@unique-ag/utils` already has a `./zod` subpath export — but it exports codecs, not brands
- Adding brands to utils would be speculative (no proven demand outside MCP)

**Verdict:** Skip. No action for utils.

---

## 3. Stays in `@unique-ag/mcp-kit` (Subpath Exports)

Everything MCP-specific or NestJS-specific stays here. Use subpath exports for clean boundaries.

### Package exports map:

```json
{
  ".":           "barrel re-export of all subpaths",
  "./errors":    "McpBaseError, DefectError, mcpInvariant, McpAuth/Validation/Tool/ProtocolError, handleMcpToolError",
  "./types":     "McpIdentity, McpContext interfaces, ResourceRef, PromptRef, PromptResult",
  "./brands":    "BearerToken, HmacSecret, Scope, UserId, ClientId, ProviderId",
  "./session":   "McpSessionStore, McpSessionRecord, InMemorySessionStore, MCP_SESSION_STORE",
  "./auth":      "McpAuthProvider, TokenValidationResult",
  "./connection":"UpstreamProviderConfig, OAuthTokenResponse, OAuth utilities"
}
```

### What's in each subpath:

| Subpath | From Ticket | Contents | Dependencies |
|---------|-------------|----------|--------------|
| `./errors` | CORE-031 | `McpBaseError`, `DefectError`, `mcpInvariant()`, all concrete MCP errors, `handleMcpToolError()` | None (pure TS) |
| `./types` | CORE-006, CORE-007 | `McpIdentity`, `ResourceRef`, `PromptRef`, `PromptResult`, `McpContext` interface | None |
| `./brands` | AUTH-001, INFRA-001 | `BearerToken`, `HmacSecret`, `Scope`, `UserId`, `ClientId`, `ProviderId` | Zod (peer) |
| `./session` | SESS-001 | `McpSessionStore`, `McpSessionRecord`, `InMemorySessionStore` | None |
| `./auth` | AUTH-001 | `McpAuthProvider`, `TokenValidationResult` | None |
| `./connection` | CONN-003 | `UpstreamProviderConfig`, `OAuthTokenResponse`, OAuth util functions | None |

### Key design decision: `mcpInvariant` vs `invariant`

The mcp-kit exports `mcpInvariant()` (not `invariant()`), which throws `DefectError` instead of plain `Error`. This carries structured metadata (error codes, stack context) for MCP exception filters. Consumer code:

```typescript
// Generic code (any package)
import { invariant } from '@unique-ag/utils';
invariant(userId, 'userId is required'); // throws Error

// MCP handler code (mcp-kit consumers)
import { mcpInvariant } from '@unique-ag/mcp-kit/errors';
mcpInvariant(userId, 'userId is required'); // throws DefectError with MCP metadata
```

---

## 4. Proposed Tickets

### Ticket 1: Add `normalizeError` and `invariant` to `@unique-ag/utils`

**Title:** feat(utils): add normalizeError and invariant utilities

**Description:**
Add two utilities to `@unique-ag/utils` that are currently duplicated or missing across the monorepo:

1. `normalizeError(error: unknown): Error` — canonical implementation from teams-mcp. Consolidates 5 copy-pasted versions.
2. `invariant(condition: unknown, message: string): asserts condition` — new utility to replace 20+ raw `if (!x) throw new Error(...)` patterns.

**Files to create:**
- `packages/utils/src/normalize-error.ts`
- `packages/utils/src/invariant.ts`
- Update `packages/utils/src/index.ts` to export both
- Add tests for both

**Acceptance criteria:**
- Both functions exported from `@unique-ag/utils`
- Tests cover edge cases (normalizeError: null, undefined, symbol, circular objects; invariant: truthy/falsy conditions, type narrowing)
- Zero new dependencies

**Story points:** 1

---

### Ticket 2: Migrate services to use `@unique-ag/utils` `normalizeError`

**Title:** refactor: replace local normalizeError with @unique-ag/utils

**Description:**
Delete local `normalizeError` implementations and import from `@unique-ag/utils` instead.

**Services to update:**
- `services/teams-mcp` — delete `src/utils/normalize-error.ts` + spec, update 5 imports
- `services/sharepoint-connector` — delete `src/utils/normalize-error.ts` + spec, update 2 imports (keep local `sanitizeError` wrapper)
- `services/outlook-mcp` — delete `src/utils/normalize-error.ts` + spec, update 10+ imports
- `services/factset-mcp` — delete `src/utils/normalize-error.ts`, update 15+ imports
- `packages/mcp-oauth` — delete `src/utils/normalize-error.ts`, update 1 import

**Acceptance criteria:**
- No local `normalizeError` implementations remain (except sharepoint-connector's `sanitizeError` wrapper which re-exports)
- All existing tests pass
- No behavioral changes

**Story points:** 2

---

### Ticket 3: Set up `@unique-ag/mcp-kit` subpath exports

**Title:** feat(mcp-kit): configure subpath exports for extracted types

**Description:**
Configure `package.json` exports map for mcp-kit with 6 subpath entry points: `./errors`, `./types`, `./brands`, `./session`, `./auth`, `./connection`. This is the packaging foundation — actual content comes from CORE-031, CORE-006, AUTH-001, etc.

**Depends on:** INFRA-001 (package scaffold)

**Acceptance criteria:**
- `package.json` `exports` field configured with all 6 subpaths
- Each subpath has a barrel `index.ts`
- TypeScript path resolution works for all subpaths
- `tsconfig.json` configured for subpath builds

**Story points:** 1

---

## Summary

| Destination | What | Why |
|-------------|------|-----|
| `@unique-ag/utils` (now) | `normalizeError()` | Duplicated in 5 packages today |
| `@unique-ag/utils` (now) | `invariant()` | 20+ raw assertion sites; universal utility |
| `@unique-ag/mcp-kit/errors` | `McpBaseError`, `DefectError`, `mcpInvariant()`, all MCP errors | MCP-specific error hierarchy |
| `@unique-ag/mcp-kit/types` | `McpIdentity`, `McpContext`, `ResourceRef`, `PromptRef` | MCP protocol types |
| `@unique-ag/mcp-kit/brands` | `BearerToken`, `HmacSecret`, `Scope`, `UserId`, `ClientId` | MCP auth branded types (no demand elsewhere) |
| `@unique-ag/mcp-kit/session` | `McpSessionStore`, `McpSessionRecord`, `InMemorySessionStore` | MCP session contracts |
| `@unique-ag/mcp-kit/auth` | `McpAuthProvider`, `TokenValidationResult` | MCP auth contracts |
| `@unique-ag/mcp-kit/connection` | `UpstreamProviderConfig`, OAuth utils | MCP upstream connection types |
| **Not created** | Separate new package | No justified need — everything fits in utils or mcp-kit |
