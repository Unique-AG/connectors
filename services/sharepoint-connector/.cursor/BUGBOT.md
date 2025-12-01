# Bugbot Rules for SharePoint-Connector

This document defines review rules for the SharePoint Connector service. Focus on Observability and Security concerns.

## General Behavior

- **One comment per line maximum**: Never add more than one review comment to the same line of code.
- **Resolve on fix**: When an issue you flagged has been addressed in a subsequent commit, resolve your comment automatically.

---

## Observability

### Metrics Labels

Prometheus metric labels must follow `lower_snake_case` convention. This applies to:

1. **Direct label definitions**: When metrics are created or recorded with labels, all label names must be `lower_snake_case`.
2. **Object field mappings**: When object fields are spread or mapped as metric labels, verify the source object's field names are also `lower_snake_case` or are transformed before being used as labels.

**Flag violations when:**
- Label names use `camelCase`, `PascalCase`, or `kebab-case`
- Object fields with non-snake-case names are passed directly as metric labels
- Dynamically constructed label names don't follow the convention

**Example violations:**
```typescript
// BAD: camelCase label
counter.add(1, { statusCode: 200 });

// BAD: Object spread with camelCase fields
const labels = { httpMethod: 'GET', statusCode: 200 };
histogram.record(duration, labels);
```

**Correct pattern:**
```typescript
// GOOD: lower_snake_case labels
counter.add(1, { status_code: 200 });

// GOOD: Object with lower_snake_case fields
const labels = { http_method: 'GET', status_code: 200 };
histogram.record(duration, labels);
```

### Logging and Data Concealment

The service supports a `conceal/disclose` policy for diagnostic data in logs. The `shouldConcealLogs()` utility from `utils/logging.util.ts` determines whether sensitive data should be redacted.

**Flag violations when:**

1. **Missing conceal check**: Logs containing potentially sensitive data (site IDs, site names, file paths, user identifiers) do not check `shouldConcealLogs` before logging.

2. **Incorrect conditional pattern**: The conceal flag is checked but the redaction functions (`smear()`, `redact()`, `redactSiteNameFromPath()`, `smearSiteIdFromPath()`, `concealIngestionKey()`) are not applied correctly.

3. **New log statements with sensitive data**: Any new log line that includes identifiable information (IDs, names, paths, URLs) must follow the established pattern:
   ```typescript
   const loggedSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
   this.logger.log(`Processing site ${loggedSiteId}`);
   ```

4. **Logging objects with sensitive fields**: When logging objects, verify that sensitive fields are redacted when conceal mode is active.

**Sensitive data types to watch for:**
- Site IDs and site names
- Drive IDs and drive names  
- File paths and file names
- User identifiers and email addresses
- Tenant IDs
- Ingestion keys
- Any SharePoint-specific identifiers

**Do NOT flag:**
- Correlation IDs (these are safe to log)
- Generic status codes and durations
- Error messages (unless they contain sensitive data)
- Item IDs in isolation (without context that could identify content)

---

## Security

Review all changes for these security concerns:

### 1. Secrets and Credentials Wrapping

All sensitive configuration values (client secrets, API keys, tokens, passwords) must be wrapped with the `Redacted<T>` class from `utils/redacted.ts`. This ensures they serialize to `[Redacted]` when accidentally logged or serialized.

**Flag when:**
- A new config field contains sensitive data but isn't transformed with `new Redacted()`
- Sensitive values are accessed via `.value` and then logged or included in error messages
- New environment variables containing secrets are added without `Redacted` wrapping in the config schema

### 2. Token and Credential Exposure Prevention

Tokens, API keys, and credentials must never appear in logs, error messages, or HTTP responses.

**Flag when:**
- Access tokens or refresh tokens are logged (even partially)
- Error handlers include raw credentials in their output
- HTTP request/response logging includes Authorization headers without redaction
- Token values are included in assertion messages or thrown errors

### 3. Authentication Mode Assertions

Authentication strategies must validate they're called with the correct `authMode` configuration. This prevents strategy misuse.

**Flag when:**
- A new authentication strategy doesn't assert its expected `authMode` at construction
- Authentication logic runs without verifying the configured mode matches
- Strategy selection logic has gaps that could allow wrong strategy execution

### 4. Private Key and Certificate Handling

Cryptographic keys and certificates require careful handling.

**Flag when:**
- Private key content is logged or included in error messages
- Private key passwords are exposed outside of the decryption operation
- Certificate thumbprints are logged at non-debug levels
- Key material is stored in memory longer than necessary
- File paths to key material are exposed in user-facing errors

### 5. Input Validation at External Boundaries

All data from external sources (SharePoint API responses, configuration, HTTP requests) must be validated before use.

**Flag when:**
- External API responses are used without null/undefined checks
- URLs from configuration or external sources aren't validated before use
- File sizes and MIME types aren't validated before processing content
- User-controlled input could influence file paths or API endpoints (path traversal risk)
- Assertions that validate external data don't provide safe error messages (avoid leaking internal structure)

---

## Things to Ignore

- Code formatting and style (handled by Biome)
- Import ordering (handled by Biome)
- Test coverage suggestions (unless explicitly security-related)
- Performance optimizations not related to security or observability
- Documentation and comments quality
