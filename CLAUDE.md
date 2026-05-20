# Connectors repo instructions

## PR titles

Before creating or updating a PR title, read `.gitcommitizen` to verify the scope matches all changed files. The pattern is `scope = last path segment` (e.g. `packages/logger` → `logger`), with one exception: `pnpm-lock.yaml` and root `package.json` require scope `deps`.

# Code Style

## Error assertions

Use `assert` from `node:assert` instead of `if` + `throw` for internal invariant checks.

```ts
// Bad
if (result.status === 'failed') {
  throw new Error(`Operation failed: ${result.error}`);
}

// Good
assert.ok(result.status !== 'failed', `Operation failed: ${result.error}`);
// or
assert.strictEqual(result.status, 'ok', `Operation failed: ${result.error}`);
```

This applies to internal preconditions, postconditions, and unreachable-state guards. Use regular `throw` only at system boundaries (user input, external API errors) where you need a specific error type or HTTP status code.
