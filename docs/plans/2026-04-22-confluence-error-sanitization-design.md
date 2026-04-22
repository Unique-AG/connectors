# Design: Confluence Connector Error Sanitization

**Ticket:** UN-19205

## Problem

The Confluence connector logs raw `error` objects under the pino `err` key in several services. The most sensitive site is `scope-management.service.ts`, which logs the raw error when `updateExternalId` fails while claiming root scope ownership.

`graphql-request` throws `ClientError` instances whose `message` and `stack` carry an embedded JSON dump of the full request (query plus raw variables). Pino's `err` serializer copies that polluted `message` and `stack` straight through to the log output. As a result, tokens, internal URLs, and other sensitive fields passed as GraphQL variables can leak into logs.

The SharePoint connector already solved this with a `sanitizeError(error)` utility. The same pattern must be applied to the Confluence connector, and the utility must live somewhere both connectors can share going forward.

## Solution

### Overview

Extract the `sanitizeError` and `normalizeError` functions (currently in `services/sharepoint-connector/src/utils/normalize-error.ts`) into the shared `@unique-ag/utils` package. Confluence-connector will consume them from the package. SharePoint-connector is left untouched in this PR to limit scope. A future ticket can migrate SharePoint to the shared utility.

In Confluence, every raw-error log site is updated to pass `sanitizeError(error)` as the `err` field value. The log key stays `err:` so existing Loki queries and dashboards keep working. Sanitization runs before pino, so pino's `err` serializer (a no-op on plain objects) cannot re-expose anything sensitive.

### Architecture

**Shared package changes (`packages/utils`):**

- New file `src/normalize-error.ts` exporting `normalizeError(unknown): Error` and `sanitizeError(unknown): object`. Byte-identical to SharePoint's current implementation.
- New file `src/__tests__/normalize-error.spec.ts` ported from SharePoint.
- `src/index.ts` re-exports both functions.
- `package.json` adds `graphql-request` and `serialize-error-cjs` as optional `peerDependencies` (mirrors the existing `typeid-js` and `zod` pattern using `peerDependenciesMeta`).

**Confluence-connector changes:**

- `package.json` adds `graphql-request` as a direct dependency (currently transitive via `@unique-ag/unique-api`).
- In each service below, `err: error` is replaced with `err: sanitizeError(error)` and `sanitizeError` is imported from `@unique-ag/utils`.

Files touched, in commit order:

1. `src/synchronization/scope-management.service.ts` (lines 108, 203) — primary ticket target.
2. `src/synchronization/ingestion.service.ts` (lines 85, 140, 167, 203).
3. `src/synchronization/confluence-content-fetcher.ts` (line 22).
4. `src/synchronization/confluence-synchronization.service.ts` (line 107).
5. `src/scheduler/tenant-sync.scheduler.ts` (lines 41, 74).
6. `src/auth/confluence-auth/strategies/oauth2lo-auth.strategy.ts` (line 63).
7. `src/utils/rate-limited-http-client.ts` (line 121).

### Error Handling

No new error paths are introduced. Every touched site already has a `catch (error)` block. The only change is what is passed to the logger inside that block. Re-throws, control flow, and metrics recording are unchanged.

### Testing Strategy

- `packages/utils`: port the SharePoint `normalize-error.spec.ts` verbatim. The function is a pure, standalone transform, so direct unit tests are the appropriate coverage. The spec already exercises Error pass-through, primitives, null/undefined, circular references, the `ClientError` message/stack strip, the structured `graphqlErrors` extraction, and the negative case where a non-`ClientError` with `response`/`request` must not be treated as GraphQL.
- `services/confluence-connector`: no new tests. The changes are mechanical replacements of the value handed to the logger. Error-path behavior, control flow, re-throws, and metrics are unchanged, and existing service tests already cover those flows.

## Out of Scope

- Migrating `services/sharepoint-connector` to consume `sanitizeError` from `@unique-ag/utils`. Separate ticket.
- Renaming the log key from `err:` to `error:`. Kept as-is for Loki query and dashboard continuity.
- Any non-error log redaction (paths, IDs, request bodies).
- Log sites that already stringify or pick scalar error fields rather than passing the raw object.

## Tasks

1. **Add `normalize-error` to `@unique-ag/utils`** — Create `src/normalize-error.ts` and its spec by porting from SharePoint. Add `graphql-request` and `serialize-error-cjs` as optional peerDependencies in `packages/utils/package.json`. Re-export from `src/index.ts`. Commit as `feat(utils): add sanitizeError and normalizeError`.
2. **Add `graphql-request` direct dependency to confluence-connector** — Bundle this with the first service-file commit so the import resolves cleanly.
3. **Sanitize errors in `scope-management.service.ts`** — Replace the two raw error log payloads with `sanitizeError(error)` and import from `@unique-ag/utils`. Commit as `fix(confluence-connector): sanitize errors in scope management`.
4. **Sanitize errors in `ingestion.service.ts`** — Replace four raw error log payloads. Commit.
5. **Sanitize errors in `confluence-content-fetcher.ts`** — Replace one raw error log payload. Commit.
6. **Sanitize errors in `confluence-synchronization.service.ts`** — Replace one raw error log payload. Commit.
7. **Sanitize errors in `tenant-sync.scheduler.ts`** — Replace two raw error log payloads. Commit.
8. **Sanitize errors in `oauth2lo-auth.strategy.ts`** — Replace one raw error log payload. Commit.
9. **Sanitize errors in `rate-limited-http-client.ts`** — Replace one raw error log payload. Commit.
10. **Verify before push** — Run `pnpm style`, `pnpm check-types`, `pnpm test` in both `packages/utils` and `services/confluence-connector`. Confirm release-please scopes match `release-please-config.json` before pushing.
