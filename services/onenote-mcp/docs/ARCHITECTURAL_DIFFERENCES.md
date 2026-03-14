# Architectural Differences to Other MCP Servers

How the OneNote MCP connector differs architecturally from the other MCP services in this repository.

---

## Service Overview

| Service | Type | External API | Auth Model | Sync | Unique Integration |
|---------|------|-------------|------------|------|-------------------|
| **onenote-mcp** | MCP server | Microsoft Graph | OAuth (delegated, per-user) | Delta + scheduled + debounced | Content, scopes, search, user matching, permissions |
| outlook-mcp | MCP server | Microsoft Graph | OAuth (delegated, per-user) | None (on-demand) | None |
| outlook-semantic-mcp | MCP server | Microsoft Graph | OAuth (delegated, per-user) | Full sync + subscriptions | File diff ingestion |
| teams-mcp | MCP server | Microsoft Graph | OAuth (delegated, per-user) | KB integration via subscriptions | Content, scopes, user mapping |
| factset-mcp | MCP server | FactSet APIs | OAuth (Zitadel) + client credentials (JWK) | None (on-demand) | None |
| confluence-connector | Connector | Confluence REST API | PAT or OAuth2LO (tenant-level) | Full sync + scheduled | Ingestion only |
| sharepoint-connector | Connector | Microsoft Graph + SharePoint REST | App-level (client secret/cert) | Full sync + scheduled | Full (auth, scopes, files, groups, users) |

---

## 1. Rate Limiting & Throttle Handling

This is the most significant difference. OneNote is the only service with a multi-layered, per-user throttle system.

### OneNote MCP (unique)

Three layers of protection:

1. **`GlobalThrottleMiddleware`** — custom Graph SDK middleware that sits in the per-user client middleware chain. Before every request, it checks a per-user throttle timestamp. If a 429/503 was recently received, it proactively waits until the `Retry-After` window expires before sending the request.

2. **`withThrottleRetry`** — a wrapper for sync-level Graph calls. If a call still fails with 429/503 after passing through the middleware (e.g., the SDK's `RetryHandler` exhausted its retries), this utility catches the error, updates the global throttle state, and retries with exponential backoff (`10s × 2^attempt`, up to 5 retries).

3. **Per-user isolation** — throttle state is a `Map<userProfileId, UserThrottleState>` so one user hitting rate limits does not block other users. This is aligned with Microsoft's OneNote API limits (120 req/min per app per user in delegated context).

Additionally, the **Unique API** fetch pipeline uses `withRetryStatus` (from `@qfetch/qfetch`) with full jitter backoff (1s–30s, up to 5 retries) on 429/502/503/504.

### Other services

| Service | Throttle handling |
|---------|-------------------|
| outlook-mcp | SDK `RetryHandler` only (5 retries, 5s delay). No custom throttle middleware. |
| outlook-semantic-mcp | SDK `RetryHandler` only. `MetricsMiddleware` tracks 429 events but does not act on them. |
| teams-mcp | SDK `RetryHandler` only. Same as outlook. |
| factset-mcp | **None.** No retry or throttle handling. |
| confluence-connector | Bottleneck rate limiter (`RateLimitedHttpClient`) + `interceptors.retry()`. Client-side rate limiting rather than server-directed backoff. |
| sharepoint-connector | SDK `RetryHandler` + `MetricsMiddleware`. Bottleneck for Unique API calls. |

**Why OneNote needed more:** OneNote's API limits are significantly stricter than other Microsoft Graph endpoints (120 req/min vs thousands for Mail). The OneNote API also does **not** return `Retry-After` headers on 429 responses, making proactive throttling with fallback defaults essential.

---

## 2. Sync Mechanism

### OneNote MCP (unique)

- **Delta sync** via the OneDrive delta API (`/me/drive/root/delta`). Only notebooks with changes since the last delta link are synced.
- **Scheduled sync** via `@nestjs/schedule` cron (default every 15 minutes). Concurrency is capped with `pLimit`.
- **Debounced sync** after create/update operations — a timer waits for `debounceMs` of inactivity before triggering, so rapid page edits don't spam syncs.
- **Concurrent sync prevention** — an `activeSyncs` set per user ensures only one sync runs at a time per user.
- **Incremental by default** — startup syncs are incremental (using the stored delta link), not full. Full sync only happens when there's no existing delta link or a `410 Gone` is received.

### Other services

| Service | Sync approach | Delta support | Concurrent sync prevention |
|---------|--------------|---------------|---------------------------|
| outlook-semantic-mcp | Full sync command + subscriptions for real-time events | No (file diff) | No |
| teams-mcp | KB integration (subscription-based) | No | No |
| confluence-connector | Full sync per tenant, scheduled | No (file diff) | Tenant-level locking |
| sharepoint-connector | Full sync, scheduled | No | No |
| outlook-mcp, factset-mcp | No sync | N/A | N/A |

**Key difference:** OneNote is the only service using Microsoft's delta query API for true incremental sync with change tracking.

---

## 3. Graph Client Middleware Chain

### OneNote MCP

```
Auth → TokenRefresh → GlobalThrottle → Metrics → Retry → Redirect → Telemetry → HTTP
```

The `GlobalThrottleMiddleware` is placed **before** `RetryHandler` so it can proactively delay requests that would hit a known throttle window, reducing wasted retry cycles.

### Other Graph-based services (outlook-mcp, outlook-semantic-mcp, teams-mcp)

```
Auth → TokenRefresh → Retry → Redirect → Telemetry → Metrics → HTTP
```

No throttle middleware. `MetricsMiddleware` position varies but it only observes, never delays.

### SharePoint connector

```
GraphAuth → TokenRefresh → Retry → Redirect → Telemetry → Metrics → HTTP
```

Similar to outlook but uses app-level auth instead of delegated user auth.

---

## 4. Error Handling & User Feedback

### OneNote MCP (unique)

- **`extractSafeGraphError`** — strips Graph errors to `{ message, code, statusCode }` for user-safe output. No other service has this.
- **`GraphErrorFilter`** — global NestJS exception filter for `GraphError`, producing structured JSON responses.
- **`statusNote`** — tool outputs include a human-readable note about throttle delays, background sync progress, or errors. Built by `GlobalThrottleMiddleware.buildStatusNote()`. This is surfaced to the end user via MCP tool annotations.
- **`dataFreshnessNote`** — the search tool includes sync freshness information (last sync time, whether a sync is in progress).

### Other services

| Service | Error handling |
|---------|---------------|
| outlook-mcp | `normalizeError` for logging. No safe extraction, no user-facing delay notes. |
| outlook-semantic-mcp | `GraphErrorFilter` (same pattern). No throttle notes. |
| teams-mcp | `GraphErrorFilter`. No throttle notes. |
| factset-mcp | `normalizeError` + `serializeError`. No structured user feedback. |
| confluence-connector | `handleErrorStatus` utility. No user feedback mechanism. |

---

## 5. MCP Tool Design & Agent Behavior

### OneNote MCP (unique)

- **Anti-chaining instructions** — `server.instructions.ts` explicitly tells the AI agent not to automatically chain tools (e.g., don't search before creating, don't verify sync before creating). Each tool's `system-prompt` annotation is narrowly scoped to trigger only on explicit user requests.
- **Informational-only metadata** — output fields like `statusNote` and `dataFreshnessNote` are described as purely informational in the schema. They explicitly state the agent should not call other tools based on their content.
- **7 tools** covering CRUD, sync management, search, and status verification.

### Other MCP services

| Service | Tool count | Anti-chaining | Agent instructions |
|---------|-----------|---------------|-------------------|
| outlook-mcp | 9 | No | Minimal |
| outlook-semantic-mcp | 9 | No | Minimal |
| teams-mcp | 4 | No | Minimal |
| factset-mcp | Many (financial data) | No | Minimal |

**Key difference:** OneNote has the most explicit agent guidance to prevent unnecessary API calls — critical given the strict OneNote rate limits.

---

## 6. Unique Platform Integration

### OneNote MCP

- **Scope hierarchy**: root → user → notebook → section group → section. Mirrors the OneNote structure.
- **Content upsert**: HTML content uploaded via write URL, keyed by `onenote:{userProfileId}:{pageId}`.
- **Permission mapping**: Resolves Drive item permissions (owners, editors, shared groups) to Unique scope accesses. Fetches group members from Graph.
- **User matching**: Maps `userProfiles.email` to Unique users for read access grants.
- **Search**: Combined vector + metadata search with scope filtering per user.
- **Unique API retry**: `withRetryStatus` middleware in the qfetch pipeline (5 retries, full jitter).

### Comparison

| Feature | OneNote | Outlook-semantic | Teams | SharePoint | Confluence |
|---------|---------|-----------------|-------|------------|-----------|
| Scope hierarchy | Deep (4 levels) | Flat | 2 levels | Deep | Flat |
| Content format | HTML | EML/email | Transcripts | Files | Pages |
| Permission sync | Yes (drive item) | No | No | Yes (SP permissions) | No |
| User matching | By email | No | By mapping | By groups/users | No |
| Unique API retry | Yes (withRetryStatus) | No | No | Bottleneck | No |

---

## 7. Unique API Retry (qfetch Pipeline)

Only the OneNote MCP uses qfetch's built-in retry middleware for the Unique API:

```typescript
pipeline(
  withBaseUrl(url),
  withHeaders(headers),
  withResponseError(),
  withRetryStatus({
    strategy: () => upto(5, fullJitter(1_000, 30_000)),
    retryableStatuses: new Set([429, 502, 503, 504]),
  }),
)(fetch);
```

- `withRetryStatus` is placed last in the pipeline (closest to `fetch`), so it intercepts raw HTTP responses before `withResponseError` throws.
- Uses AWS-style full jitter: `random(0, min(30_000, 1_000 × 2^n))`.
- Covers all Unique API calls: content upsert, upload, search, scope creation, user lookup.

Other services using `@unique-ag/unique-api` or raw fetch do not have this retry layer. SharePoint uses Bottleneck for client-side rate limiting on Unique calls but not server-directed retry.

---

## 8. Tool Output Design — Status & Error Reporting to the Frontend

The most distinctive pattern in the OneNote MCP tools is how they communicate runtime context (throttle delays, sync state, errors) back through the AI agent to the end user. No other service does this.

### The Pattern

Every OneNote tool output schema includes structured fields that the agent is explicitly instructed to relay to the user:

| Field | Used by | Purpose |
|-------|---------|---------|
| `statusNote` | create-page, update-page, create-notebook, start-sync, stop-sync, verify-sync-status | Human-readable note about throttle delays, background sync status, or errors |
| `syncStatus.dataFreshnessNote` | search-onenote | Data freshness information — last sync time, ongoing sync, throttle state |

### How `statusNote` is Built

`GlobalThrottleMiddleware.buildStatusNote(userProfileId, throttleWaitMs, extras[])` assembles the note from multiple signals:

1. **Throttle delay** — if the request was delayed waiting for a 429 backoff: `"This request was delayed by ~12s because Microsoft OneNote is temporarily rate-limiting requests."`
2. **Ongoing throttle** — if the API is still rate-limited for upcoming requests: `"OneNote API is still rate-limited — subsequent requests may be delayed by up to 8s."`
3. **Operation-specific context** — extras added by each tool, e.g.: `"The page was created successfully. A background sync is running so it will appear in search results within the next couple of minutes."`

On errors, the same mechanism produces a note like: `"This request was delayed by ~20s... The page could not be created: Notebook not found."`

### How `dataFreshnessNote` is Built

The search tool's `buildSyncStatus()` method checks:

- `OneNoteDeltaService.getDeltaStatus()` — when was the last sync, what was its status
- `OneNoteSyncService.isSyncRunning()` — is a sync in progress right now
- `GlobalThrottleMiddleware.currentThrottleRemainingMs()` — is the API currently throttled

And produces notes like:
- `"Data is up to date."` (synced within 2 minutes)
- `"The last sync was 15 minutes ago. Results might not include very recent changes."` (stale)
- `"A background sync is currently running — the latest data may not be reflected yet."` (syncing)
- `"Microsoft OneNote is temporarily rate-limiting requests. Background syncs may be delayed by up to 10s."` (throttled)

### The `tool-format-information` Annotation

OneNote is the **only service** that uses the `unique.app/tool-format-information` MCP annotation. This annotation tells the AI agent **how to format and relay tool output** to the user:

```
Always relay the statusNote to the user when it is present.
```

```
Always relay the syncStatus.dataFreshnessNote to the user.
```

This is critical because without it, the agent might silently discard throttle delay information or sync freshness warnings rather than presenting them to the user.

### Error Handling: Return vs Throw

OneNote tools **never throw** for expected failures. They return structured responses:

```json
{
  "success": false,
  "message": "Failed to create page: Notebook \"Research\" not found",
  "statusNote": "This request was delayed by ~8s because Microsoft OneNote is temporarily rate-limiting requests."
}
```

This ensures the user always gets both the error explanation and the throttle context. If the tool threw an exception instead, the `statusNote` would be lost.

### How Other Services Handle This

| Service | Status fields | `tool-format-information` | Error handling | Agent relay instructions |
|---------|--------------|--------------------------|----------------|------------------------|
| **OneNote MCP** | `statusNote`, `dataFreshnessNote` | Yes (all 7 tools) | Return `success: false` + status | "Always relay statusNote/dataFreshnessNote" |
| outlook-mcp | None | No | Throws `InternalServerErrorException` | None |
| outlook-semantic-mcp | `status`, `message` (connection state only) | No | Mixed return/throw | None |
| teams-mcp | `status`, `message` (integration state only) | No | Return for expected cases | None |
| factset-mcp | None | No | Throws `InternalServerErrorException` | None |

Key differences:

- **Only OneNote** surfaces rate-limit delays and sync freshness to the user.
- **Only OneNote** uses `tool-format-information` to instruct the agent on output formatting.
- **Only OneNote** returns structured errors with context instead of throwing. This preserves throttle information that would otherwise be lost in an exception.
- **Outlook semantic** and **Teams** have `status`/`message` fields but only for connection/subscription state, not for runtime performance feedback.
- **Outlook** and **Factset** have no output schemas at all — tools return raw API responses and throw on errors.

### The `system-prompt` Anti-Chaining Pattern

Each OneNote tool's `system-prompt` is narrowly scoped to prevent the agent from calling it unnecessarily. For example, `search_onenote` states:

> Use this tool ONLY when the user explicitly asks to search, find, or look up existing OneNote content.

And the `dataFreshnessNote` schema description explicitly states:

> This is informational context for the user. Do NOT call other tools (like start_onenote_sync) based on this field.

No other service has this level of agent behavior control. This was added specifically because broad system prompts caused the agent to chain `search → verify-sync → start-sync → search → create` when the user only asked to create a page.

---

## Summary: What Makes OneNote MCP Different

1. **Per-user throttle isolation** — the only service tracking 429 state per user, not globally or not at all.
2. **Multi-layered retry** — middleware-level proactive waiting + sync-level retry with exponential backoff + Unique API pipeline retry.
3. **Delta sync** — the only service using Graph's delta query API for true incremental sync.
4. **Concurrent sync prevention** — per-user locking with debouncing for create/update operations.
5. **Agent anti-chaining** — the most explicit instructions to prevent the AI from unnecessary tool calls.
6. **User-facing throttle feedback** — `statusNote` informs users about API delays in human-readable language.
7. **Permission mapping** — resolves OneDrive sharing permissions to Unique scope accesses.
8. **Structured tool output with relay instructions** — the only service using `tool-format-information` to instruct the agent to surface runtime context (throttle delays, sync freshness, errors) to the user. Other services either throw exceptions or return raw data with no formatting guidance.
