# PR Proposal

## Title

fix(sharepoint-connector): add JSON string parsing for logsDiagnosticsConfigEmitPolicy env var

## Description

- Fix startup crash caused by `logsDiagnosticsConfigEmitPolicy` receiving a JSON string from the env var instead of a parsed array, by adding `z.preprocess` with JSON.parse coercion
- Extract reusable `parseJsonOrPassthrough` utility in `config.util.ts` for env vars that carry JSON-encoded values in union schemas
- Add schema-level tests for `AppConfigSchema` to validate parsing from string inputs as environment variables deliver them
