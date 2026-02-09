# Design: Add Smeared/Redacted Protection to Confluence Connector Config Fields

## Problem

The confluence-connector already uses `Redacted` for secrets (apiToken, PAT, password, zitadelClientSecret), but lacks the `Smeared` class that the sharepoint-connector uses for diagnostic data — identifiers like emails, usernames, and company/user IDs that help debugging but shouldn't appear in full in production logs.

Without smearing, these identifiers leak in plain text whenever the config is logged or serialized, posing a data exposure risk in production.

## Solution

### Overview

Port the `Smeared` class pattern from the sharepoint-connector. `Smeared` wraps diagnostic data that is visible in full during development but partially masked in production. The behavior is controlled by a `LOGS_DIAGNOSTICS_DATA_POLICY` environment variable (default: `conceal`).

This is distinct from `Redacted`, which **always** hides the value regardless of environment.

### Architecture

**New files:**
- `src/utils/logging.util.ts` — `smear()` function that partially masks strings (e.g., `admin@acme.com` → `*****@***e.com`)
- `src/utils/smeared.ts` — `Smeared` class, `createSmeared()` factory, `isSmearingActive()` helper

**Modified files:**
- `src/config/app.config.ts` — Add `logsDiagnosticsDataPolicy` field with `LOGS_DIAGNOSTICS_DATA_POLICY` env var (enum: `conceal` | `disclose`, default: `conceal`)
- `src/config/confluence.schema.ts` — Transform `auth.email` and `auth.username` through `createSmeared()`
- `src/config/unique.schema.ts` — Transform `serviceExtraHeaders` `x-company-id` and `x-user-id` values through `createSmeared()`
- `.env.example` — Add `LOGS_DIAGNOSTICS_DATA_POLICY` documentation

### Field Classification

| Field | Protection | Reason |
|---|---|---|
| `auth.apiToken` | `Redacted` (existing) | Secret |
| `auth.token` (PAT) | `Redacted` (existing) | Secret |
| `auth.password` | `Redacted` (existing) | Secret |
| `zitadelClientSecret` | `Redacted` (existing) | Secret |
| `zitadelProjectId` | `Redacted` (existing) | Secret |
| `auth.email` | **`Smeared` (new)** | Identifier |
| `auth.username` | **`Smeared` (new)** | Identifier |
| `serviceExtraHeaders[x-company-id]` | **`Smeared` (new)** | Identifier |
| `serviceExtraHeaders[x-user-id]` | **`Smeared` (new)** | Identifier |
| `baseUrl`, URLs, labels, etc. | Plain (unchanged) | Non-sensitive config |

### Error Handling

No special error handling needed — `Smeared` is a pure wrapper applied at config parse time via Zod transforms. If smearing fails (shouldn't happen for strings), the existing schema validation error path handles it.

### Testing Strategy

- **Unit tests for `smear()`** — pure function, test edge cases (short strings, empty, null, various lengths)
- **Unit tests for `Smeared` class** — test `toString()`/`toJSON()` behavior with active/inactive smearing
- **Update existing `tenant-config-loader.spec.ts`** — verify that parsed config returns `Smeared` instances for email, username, and header values

## Out of Scope

- Config diagnostics service (sharepoint has `ConfigDiagnosticsService` — separate concern)
- `logsDiagnosticsConfigEmitPolicy` (sharepoint feature, not needed yet)
- Runtime log message smearing (this design only covers config field wrapping)
- Helm chart / values.yaml / values.schema.json changes

## Tasks

1. **Create `smear()` utility** — Port `smear()` function from sharepoint-connector to `src/utils/logging.util.ts`. Include unit tests for edge cases.
2. **Create `Smeared` class** — Port `Smeared` class, `createSmeared()`, and `isSmearingActive()` to `src/utils/smeared.ts`. Include unit tests.
3. **Add `logsDiagnosticsDataPolicy` to app config** — Add the `LOGS_DIAGNOSTICS_DATA_POLICY` env var to `app.config.ts` with `conceal`/`disclose` enum and default `conceal`. Update `.env.example`.
4. **Apply Smeared to confluence schema** — Transform `auth.email` and `auth.username` fields through `createSmeared()` in `confluence.schema.ts`.
5. **Apply Smeared to unique schema** — Transform `serviceExtraHeaders` `x-company-id` and `x-user-id` values through `createSmeared()` in `unique.schema.ts`.
6. **Update existing loader tests** — Adjust `tenant-config-loader.spec.ts` assertions to account for `Smeared` wrapper on affected fields.
