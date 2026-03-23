# Package Extraction Proposal

## Executive Summary

After evaluating all 36 cross-cutting candidates against the four criteria (standalone usefulness, minimal deps, separate import need, version stability), I recommend **Option A: zero extraction**. Everything stays in `@unique-ag/mcp-kit` with subpath exports. The overhead of separate npm packages is not justified for any candidate at this stage.

---

## Proposed Options

### Option A: Zero extraction — subpath exports only (RECOMMENDED)

**No new packages.** `@unique-ag/mcp-kit` uses `package.json` `exports` to expose subpath entry points:

```json
{
  "exports": {
    ".": "./dist/index.js",
    "./errors": "./dist/errors/index.js",
    "./types": "./dist/types/index.js",
    "./session": "./dist/session/index.js",
    "./auth": "./dist/auth/index.js",
    "./testing": "./dist/testing/index.js"
  }
}
```

Consumers can import precisely what they need:
```typescript
import { invariant, DefectError } from '@unique-ag/mcp-kit/errors';
import { McpIdentity, UserId } from '@unique-ag/mcp-kit/types';
import { McpSessionStore } from '@unique-ag/mcp-kit/session';
```

**Why this works:**
- Tree-shaking eliminates unused code — consumers pay only for what they import
- No diamond-dependency version conflicts between `@unique-ag/mcp-errors` and `@unique-ag/mcp-kit`
- Zero publish/version coordination overhead
- Subpath exports provide the same DX as separate packages
- All candidates share the same two deps (zod, @modelcontextprotocol/sdk)

---

### Option B: Minimal extraction — one shared types/errors package

**1 new package:** `@unique-ag/mcp-types`

| Package | Exports | Deps | Est. size |
|---------|---------|------|-----------|
| `@unique-ag/mcp-types` | Error hierarchy, `invariant()`, `McpIdentity`, branded types, `McpSessionStore` interface, `McpAuthProvider` interface, `UpstreamProviderConfig` interface | `zod` (peer) | ~8 KB min |
| `@unique-ag/mcp-kit` | Everything else (NestJS framework) — imports `@unique-ag/mcp-types` | `@unique-ag/mcp-types`, `@nestjs/*`, `@modelcontextprotocol/sdk`, `zod` | rest |

**Who benefits:** Someone writing a raw MCP server with `@modelcontextprotocol/sdk` who wants the error classes and identity types without pulling in NestJS.

**Trade-offs:**
- (+) Clean separation of pure TS from NestJS
- (-) Two packages to version and publish for every release
- (-) `@unique-ag/mcp-kit` must re-export everything from `@unique-ag/mcp-types` for ergonomics, creating a barrel-re-export tax
- (-) Breaking changes in types force coordinated releases of both packages
- (-) The "raw SDK" consumer persona is hypothetical — all current consumers use the full framework

---

### Option C: Aggressive extraction — three+ packages

| Package | Exports | Deps |
|---------|---------|------|
| `@unique-ag/mcp-errors` | `McpBaseError`, all failure subclasses, `DefectError`, `invariant()`, `handleMcpToolError()` | none |
| `@unique-ag/mcp-types` | `McpIdentity`, branded types, `McpSessionStore`, `McpAuthProvider`, `ResourceRef`, `PromptRef` | `zod` (peer) |
| `@unique-ag/mcp-oauth-utils` | `UpstreamProviderConfig`, `OAuthTokenResponse`, `buildAuthorizationUrl()`, `exchangeCode()`, `refreshToken()`, PKCE utils | none |
| `@unique-ag/mcp-kit` | NestJS framework (imports all above) | all above + `@nestjs/*` + `@modelcontextprotocol/sdk` |

**Trade-offs:**
- (+) Maximum granularity — consumers pick exactly what they need
- (-) 4 packages to version, publish, and coordinate
- (-) `@unique-ag/mcp-errors` is ~2 KB — npm package overhead (README, LICENSE, CI, changelogs) exceeds the code
- (-) `@unique-ag/mcp-oauth-utils` duplicates what `@modelcontextprotocol/sdk` already provides
- (-) Consumers must manage 4 dependency versions; diamond deps become likely
- (-) No existing consumer would use just one of these

---

## Recommendation

**Option A: zero extraction with subpath exports.**

Rationale:

1. **No real standalone consumer exists.** Every consumer of `McpIdentity` or `invariant()` is building an MCP server with the full framework. The "someone using just the raw SDK" persona does not exist today and is speculative.

2. **Subpath exports solve the DX problem without the overhead.** `import { invariant } from '@unique-ag/mcp-kit/errors'` is functionally identical to `import { invariant } from '@unique-ag/mcp-errors'` but with zero package management cost.

3. **The dependency footprint is already minimal.** The pure-TS candidates (errors, types, brands) have only `zod` as a runtime dep. Extracting them saves consumers nothing — they already need `zod` for the framework.

4. **Premature extraction is expensive to undo.** If we extract now and the API changes during Sprint 1-3, we pay the cost of coordinated semver bumps across multiple packages. If we wait and a real use case emerges, extraction from subpath exports is mechanical (move files, publish new package, add re-export).

5. **Monorepo precedent.** This repo already has `@unique-ag/utils`, `@unique-ag/logger`, etc. Those packages exist because they serve multiple apps (connectors). The mcp-kit types serve exactly one framework — there is no multi-app consumption scenario.

**The decision to extract should be demand-driven, not supply-driven.** When a concrete consumer needs the types without NestJS, extraction from subpath exports takes an afternoon. Until then, keep it simple.

---

## What Stays in `@unique-ag/mcp-kit`

Everything. Organized as subpath exports:

| Subpath | Contents | Ticket(s) |
|---------|----------|-----------|
| `@unique-ag/mcp-kit/errors` | `McpBaseError`, all failure classes, `DefectError`, `invariant()`, `handleMcpToolError()` | CORE-031 |
| `@unique-ag/mcp-kit/types` | `McpIdentity`, branded types (`UserId`, `ClientId`, `BearerToken`, `HmacSecret`, `Scope`, `ProviderId`), `TokenValidationResult`, `McpAuthProvider` interface | CORE-006, AUTH-001, INFRA-001 |
| `@unique-ag/mcp-kit/session` | `McpSessionStore`, `McpSessionRecord`, `InMemorySessionStore` | SESS-001 |
| `@unique-ag/mcp-kit/connection` | `UpstreamProviderConfig`, `OAuthTokenResponse`, OAuth utility functions | CONN-003 |
| `@unique-ag/mcp-kit/context` | `ResourceRef`, `PromptRef`, `PromptResult`, `McpContext` interface | CORE-007 |
| `@unique-ag/mcp-kit/sdk` | Elicitation/sampling/tasks option types and response schemas | SDK-001..007 |
| `@unique-ag/mcp-kit/auth` | NestJS auth module, guards, providers | AUTH-001..009 |
| `@unique-ag/mcp-kit/testing` | `McpTestingModule`, `McpTestClient` | TEST-001, TEST-002 |
| `@unique-ag/mcp-kit` | Decorators, module config, handlers, pipeline, transports, proxy | Everything else |

This gives consumers fine-grained imports and tree-shaking without any package boundary overhead.

---

## Proposed New Tickets

### INFRA-002: Configure subpath exports in package.json
Set up `exports` map in `@unique-ag/mcp-kit/package.json` with all subpath entry points. Configure `typesVersions` for TypeScript resolution. Verify tree-shaking works with both bundlers (esbuild, rollup) and direct Node.js imports. Add CI check that subpath exports resolve correctly.

### INFRA-003: Add barrel export linting rule
Add a Biome or custom lint rule that prevents circular imports between subpath modules (e.g., `errors/` must not import from `session/`). This maintains the clean layering that would be enforced by package boundaries, without the package overhead.

---

## Candidate-by-Candidate Evaluation

| Candidate | Standalone useful? | Minimal deps? | Separate import need? | Stable API? | Verdict |
|-----------|-------------------|---------------|----------------------|-------------|---------|
| `invariant()` + `DefectError` | Marginally — but `tiny-invariant` exists | Zero deps | No — always used with other errors | Yes | Stay (subpath) |
| `McpBaseError` + failures | Only for MCP error handling | Zero deps | Maybe for client-side error parsing | Mostly stable | Stay (subpath) |
| `McpIdentity` + branded types | Only for MCP identity | `zod` peer | No — always used within framework | Yes | Stay (subpath) |
| `TokenValidationResult` / auth brands | No — MCP-auth specific | `zod` peer | No | Yes | Stay (subpath) |
| `McpSessionStore` interface | Marginally — for custom store authors | Zero deps | No — store impls live in framework | Yes | Stay (subpath) |
| `UpstreamProviderConfig` + OAuth utils | No — generic OAuth exists elsewhere | Zero deps | No | Unstable (Sprint 8) | Stay (subpath) |
| SDK response/option types | No — tightly coupled to framework | `zod` peer | No | Unstable (Sprint 5) | Stay (subpath) |
