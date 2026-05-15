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
