# Design: Fix `logsDiagnosticsConfigEmitPolicy` env var parsing

## Problem

The `logsDiagnosticsConfigEmitPolicy` field in `AppConfigSchema` uses `z.union([z.literal('none'), z.array(z.enum(ConfigEmitPolicy))])` but environment variables are always strings. When the ConfigMap delivers `'["on_startup","per_sync"]'`, the Zod schema receives a raw string — not a parsed array — causing both union branches to fail:

- `z.literal('none')` fails because the value is `'["on_startup","per_sync"]'`, not `'none'`
- `z.array(...)` fails because the value is a string, not an array

This crashes the application on startup with `TypeError: Invalid config for "app"`.

### Why it wasn't caught

Three layers of validation exist, but the bug falls in the gap between them:

1. **Helm values schema** (`values.schema.json`) validates the value is a string — correct for ConfigMap values, passes fine
2. **Helm template tests** only cover `tenant-config.yaml` rendering, not the env ConfigMap
3. **Application unit tests** mock `ConfigService.get()` returning already-parsed JavaScript arrays — bypassing Zod schema parsing entirely

No test validates the boundary: "given this string from an env var, can the Zod schema parse it?"

## Solution

### Overview

Add a `z.preprocess` step that attempts `JSON.parse` on string inputs before the union validation. Extract the preprocess function as a reusable utility `parseJsonOrPassthrough` in `config.util.ts`.

The function tries `JSON.parse` on string inputs. If parsing succeeds (e.g., `'["on_startup","per_sync"]'` → array), the parsed value is passed to the schema. If parsing fails (e.g., `'none'` is not valid JSON), the original string passes through — which then matches `z.literal('none')`.

Non-string inputs (like arrays from `prefault` defaults) pass through untouched.

### Architecture

**New utility in `config.util.ts`:**

```typescript
export const parseJsonOrPassthrough = (val: unknown): unknown => {
  if (typeof val !== 'string') return val;
  try { return JSON.parse(val); } catch { return val; }
};
```

This complements the existing `parseJsonEnvironmentVariable` (a Zod schema builder for `.pipe()` usage that throws on invalid JSON) and `parseCommaSeparatedArray` (a plain function for comma-delimited strings).

**Updated schema in `app.config.ts`:**

```typescript
logsDiagnosticsConfigEmitPolicy: z
  .preprocess(
    parseJsonOrPassthrough,
    z.union([z.literal('none'), z.array(z.enum(ConfigEmitPolicy))]),
  )
  .prefault([ConfigEmitPolicy.ON_STARTUP, ConfigEmitPolicy.PER_SYNC])
  .describe(
    'Controls when configuration is logged. Array of triggers: on_startup logs once on start, per_sync logs at each site sync. Use "none" to disable.',
  ),
```

### Error Handling

- Valid JSON string → parsed and validated against union
- `'none'` literal → JSON.parse fails silently, string passes through to `z.literal('none')` match
- Invalid JSON + not `'none'` → JSON.parse fails silently, string passes through, fails union validation with descriptive Zod error
- Invalid enum values in array → JSON.parse succeeds, `z.array(z.enum(...))` rejects with Zod error

### Testing Strategy

**New `app.config.spec.ts`** — schema-level tests for `AppConfigSchema` that validate parsing from string inputs (as env vars deliver them):

- JSON string `'["on_startup","per_sync"]'` parses to array
- JSON string `'["on_startup"]'` parses to single-element array
- `'none'` string passes through as literal
- `undefined` input produces prefault default `['on_startup', 'per_sync']`
- Invalid JSON string fails validation
- Valid JSON with invalid enum values fails validation

**New `config.util.spec.ts`** (or extend existing) — unit tests for `parseJsonOrPassthrough`:

- Parses valid JSON strings (arrays, objects)
- Returns original string when JSON.parse fails
- Passes through non-string values (arrays, objects, undefined, null)

## Out of Scope

- Refactoring `parseJsonEnvironmentVariable` to share implementation with `parseJsonOrPassthrough` — they serve different purposes (Zod schema builder vs plain preprocess function)
- Adding helm-unittest tests for the env ConfigMap template
- Integration tests that exercise the full config loading pipeline from env vars

## Tasks

1. **Add `parseJsonOrPassthrough` utility** — Create the utility function in `config.util.ts` with unit tests in `config.util.spec.ts`
2. **Fix `logsDiagnosticsConfigEmitPolicy` schema** — Wrap the union with `z.preprocess(parseJsonOrPassthrough, ...)` in `app.config.ts`
3. **Add `AppConfigSchema` tests** — Create `app.config.spec.ts` with schema-level tests for the `logsDiagnosticsConfigEmitPolicy` field, validating string inputs, defaults, and error cases
